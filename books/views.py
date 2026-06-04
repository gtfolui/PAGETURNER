import datetime
import json
from collections import Counter, defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Activity,
    Book,
    FriendRequest,
    Friendship,
    Notification,
    ReadingChallenge,
    Report,
    UserBook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_or_create_challenge(user) -> ReadingChallenge:
    year = timezone.now().year
    challenge, _ = ReadingChallenge.objects.get_or_create(
        user=user, year=year, defaults={"goal": 20}
    )
    return challenge


def _books_read_this_year(user) -> int:
    year = timezone.now().year
    return UserBook.objects.filter(
        user=user,
        shelf="read",
        updated_at__year=year,
    ).count()


def _shelf_counts(user) -> dict:
    rows = (
        UserBook.objects.filter(user=user)
        .values("shelf")
        .annotate(n=Count("id"))
    )
    counts = {"reading": 0, "read": 0, "want": 0, "favorites": 0}
    for row in rows:
        counts[row["shelf"]] = row["n"]
    return counts


def _friend_users(user):
    return User.objects.filter(followers__user=user).select_related("profile")


def _needs_verification(user) -> bool:
    """True when this user can't take social actions because their email
    is unverified and the feature flag is on."""
    from django.conf import settings
    if not getattr(settings, "REQUIRE_EMAIL_VERIFICATION", False):
        return False
    profile = getattr(user, "profile", None)
    return bool(profile and not profile.is_email_verified)


def _profanity_filter(text: str) -> str:
    """Replace blocklisted words with asterisks. Cheap, conservative, and
    bypassable — real moderation uses ML services, but this is the project's
    first line of defence and makes the intent explicit in the code."""
    from django.conf import settings
    blocklist = getattr(settings, "PROFANITY_BLOCKLIST", []) or []
    if not text or not blocklist:
        return text
    out = text
    lower = text.lower()
    for word in blocklist:
        idx = 0
        while True:
            i = lower.find(word, idx)
            if i == -1:
                break
            out = out[:i] + "*" * len(word) + out[i + len(word):]
            idx = i + len(word)
    return out


def _hourly_friend_request_count(user) -> int:
    from django.conf import settings
    cutoff = timezone.now() - datetime.timedelta(hours=1)
    return FriendRequest.objects.filter(sender=user, created_at__gte=cutoff).count()


def _log_activity(user):
    """Record that this user did *something* today. Used by the streak/heatmap."""
    from .models import DailyActivity
    today = timezone.localdate()
    obj, created = DailyActivity.objects.get_or_create(user=user, date=today)
    if not created:
        DailyActivity.objects.filter(pk=obj.pk).update(actions=obj.actions + 1)


def _current_streak(user) -> int:
    """Length of consecutive days (counting today or yesterday as the head)
    that the user has logged any activity."""
    from .models import DailyActivity
    today = timezone.localdate()
    qs = DailyActivity.objects.filter(user=user).order_by("-date")
    if not qs.exists():
        return 0
    dates = list(qs.values_list("date", flat=True)[:400])
    head = dates[0]
    # Allow yesterday as the head so the user doesn't lose their streak the moment midnight rolls over.
    if (today - head).days > 1:
        return 0
    streak = 1
    for i in range(1, len(dates)):
        if (dates[i - 1] - dates[i]).days == 1:
            streak += 1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@login_required
def home(request):
    user = request.user
    challenge = _get_or_create_challenge(user)
    read_count = _books_read_this_year(user)
    goal = challenge.goal
    pct = min(100, round(read_count / goal * 100)) if goal else 0

    currently_reading = (
        UserBook.objects.filter(user=user, shelf="reading")
        .select_related("book")
        .order_by("-updated_at")[:5]
    )

    # Recommendations: books not on any of the user's shelves
    shelved_ids = UserBook.objects.filter(user=user).values_list("book_id", flat=True)
    recommendations = (
        Book.objects.exclude(id__in=shelved_ids)
        .order_by("-avg_rating", "title")[:6]
    )

    # Friends' recent activity (or global if no friends followed yet)
    friend_ids = Friendship.objects.filter(user=user).values_list("friend_id", flat=True)
    if friend_ids:
        feed_qs = Activity.objects.filter(user_id__in=friend_ids)
    else:
        feed_qs = Activity.objects.exclude(user=user)
    home_feed = feed_qs.select_related("user__profile", "book")[:3]

    ctx = {
        "active_page": "home",
        "challenge": challenge,
        "challenge_pct": pct,
        "challenge_left": max(0, goal - read_count),
        "challenge_read": read_count,
        "currently_reading": currently_reading,
        "recommendations": recommendations,
        "home_feed": home_feed,
    }
    return render(request, "books/home.html", ctx)


@login_required
def shelves(request):
    shelf = request.GET.get("shelf", "reading")
    if shelf not in {"reading", "read", "want", "favorites"}:
        shelf = "reading"

    items = (
        UserBook.objects.filter(user=request.user, shelf=shelf)
        .select_related("book")
        .order_by("-updated_at")
    )
    counts = _shelf_counts(request.user)

    return render(
        request,
        "books/shelves.html",
        {
            "active_page": "shelves",
            "current_shelf": shelf,
            "items": items,
            "counts": counts,
        },
    )


@login_required
def discover(request):
    from . import services

    genre = request.GET.get("genre", "all")
    q = request.GET.get("q", "").strip()

    # Local catalog (already-imported books)
    qs = Book.objects.all()
    if genre != "all":
        qs = qs.filter(genre=genre)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(author__icontains=q))
    local_books = list(qs.order_by("-avg_rating", "title")[:24])

    # Live remote results (Google Books → Open Library fallback). The facade
    # decides which provider to hit; we only render them when there's a query.
    remote_results: list[dict] = []
    if q:
        remote_results = services.book_search(q, max_results=12)
        # De-duplicate against books already in the local catalog.
        local_external_ids = set(
            Book.objects.filter(external_id__in=[r["external_id"] for r in remote_results])
            .values_list("external_id", flat=True)
        )
        remote_results = [r for r in remote_results if r["external_id"] not in local_external_ids]

    return render(
        request,
        "books/discover.html",
        {
            "active_page": "discover",
            "books": local_books,
            "remote_results": remote_results,
            "current_genre": genre,
            "query": q,
            "genres": Book.GENRE_CHOICES,
        },
    )


@login_required
def challenge_page(request):
    user = request.user
    challenge = _get_or_create_challenge(user)
    read_count = _books_read_this_year(user)
    goal = challenge.goal
    pct = min(100, round(read_count / goal * 100)) if goal else 0

    pages_read = (
        UserBook.objects.filter(user=user, shelf="read", updated_at__year=challenge.year)
        .aggregate(s=models_sum("book__pages"))
        .get("s") or 0
    )

    year_books = (
        UserBook.objects.filter(user=user, shelf="read", updated_at__year=challenge.year)
        .select_related("book")
        .order_by("-updated_at")
    )

    return render(
        request,
        "books/challenge.html",
        {
            "active_page": "challenge",
            "challenge": challenge,
            "challenge_read": read_count,
            "challenge_pct": pct,
            "challenge_left": max(0, goal - read_count),
            "challenge_pages": pages_read,
            "year_books": year_books,
        },
    )


# Workaround so we can call Sum without importing it everywhere
def models_sum(field):
    from django.db.models import Sum

    return Sum(field)


@login_required
def stats(request):
    user = request.user
    read_ubs = UserBook.objects.filter(user=user, shelf="read").select_related("book")

    total_books = read_ubs.count()
    total_pages = sum(ub.book.pages for ub in read_ubs)
    avg_rating = (
        UserBook.objects.filter(user=user, shelf="read", rating__gt=0)
        .aggregate(a=Avg("rating"))
        .get("a")
        or 0
    )
    reviews_written = (
        UserBook.objects.filter(user=user).exclude(review="").count()
    )

    # Top genres
    genre_counter = Counter(ub.book.genre for ub in read_ubs)
    genre_palette = {
        "fantasy": "#C4922A",
        "scifi": "#4A6741",
        "literary": "#6B4C35",
        "mystery": "#8B3E2A",
        "nonfiction": "#3A5A8A",
        "romance": "#5A3A5A",
    }
    genre_labels = dict(Book.GENRE_CHOICES)
    top_genres_raw = genre_counter.most_common(5)
    max_genre = top_genres_raw[0][1] if top_genres_raw else 1
    top_genres = [
        {
            "name": genre_labels.get(g, g.title()),
            "count": n,
            "color": genre_palette.get(g, "#C4922A"),
            "pct": round(n / max_genre * 100),
        }
        for g, n in top_genres_raw
    ]

    # Books per year (last 5 years)
    year_counter = Counter()
    for ub in read_ubs:
        year_counter[ub.updated_at.year] += 1
    this_year = timezone.now().year
    years = list(range(this_year - 4, this_year + 1))
    year_data_raw = [{"year": y, "count": year_counter.get(y, 0)} for y in years]
    max_year = max((d["count"] for d in year_data_raw), default=1) or 1
    year_data = [
        {**d, "height_pct": round(d["count"] / max_year * 100) if max_year else 0}
        for d in year_data_raw
    ]

    return render(
        request,
        "books/stats.html",
        {
            "active_page": "stats",
            "total_books": total_books,
            "total_pages": total_pages,
            "avg_rating": round(avg_rating, 1),
            "reviews_written": reviews_written,
            "top_genres": top_genres,
            "year_data": year_data,
        },
    )


@login_required
def feed(request):
    user = request.user
    friend_ids = Friendship.objects.filter(user=user).values_list("friend_id", flat=True)
    if friend_ids:
        qs = Activity.objects.filter(user_id__in=friend_ids)
    else:
        # Show global feed (excluding self) if not following anyone
        qs = Activity.objects.exclude(user=user)
    activities = qs.select_related("user__profile", "book")[:50]
    return render(
        request,
        "books/feed.html",
        {"active_page": "feed", "activities": activities},
    )


@login_required
def friends(request):
    user = request.user
    following_ids = set(
        Friendship.objects.filter(user=user).values_list("friend_id", flat=True)
    )
    pending_sent_ids = set(
        FriendRequest.objects.filter(sender=user, status="pending")
        .values_list("receiver_id", flat=True)
    )
    incoming = (
        FriendRequest.objects.filter(receiver=user, status="pending")
        .select_related("sender", "sender__profile")
    )
    # Suggest everyone except self + already-followed
    candidates = (
        User.objects.exclude(id=user.id)
        .select_related("profile")
        .annotate(books_read=Count("user_books", filter=Q(user_books__shelf="read")))
    )
    people = []
    for u in candidates:
        currently = (
            UserBook.objects.filter(user=u, shelf="reading")
            .select_related("book")
            .first()
        )
        people.append({
            "user": u,
            "books_read": u.books_read,
            "currently": currently.book if currently else None,
            "is_friend": u.id in following_ids,
            "is_pending": u.id in pending_sent_ids,
        })

    return render(
        request,
        "books/friends.html",
        {
            "active_page": "friends",
            "people": people,
            "incoming_requests": incoming,
        },
    )


@login_required
def notifications(request):
    notifs = Notification.objects.filter(user=request.user)
    return render(
        request,
        "books/notifications.html",
        {"active_page": "notifications", "notifications": notifs},
    )


@login_required
def profile(request, username=None):
    target = (
        get_object_or_404(User, username=username) if username else request.user
    )
    read_books = (
        UserBook.objects.filter(user=target, shelf="read")
        .select_related("book")
        .order_by("-updated_at")[:12]
    )
    counts = _shelf_counts(target)
    reviews_count = UserBook.objects.filter(user=target).exclude(review="").count()
    friend_count = Friendship.objects.filter(user=target).count()

    return render(
        request,
        "books/profile.html",
        {
            "active_page": "profile",
            "target_user": target,
            "is_own_profile": target == request.user,
            "read_books": read_books,
            "books_read_count": counts["read"],
            "reviews_count": reviews_count,
            "friend_count": friend_count,
        },
    )


# ---------------------------------------------------------------------------
# Actions (POST endpoints — return JSON or redirect)
# ---------------------------------------------------------------------------
@login_required
def book_detail(request, book_id):
    """Return JSON for the modal: book details, user's state, community
    reviews, rating breakdown, author bibliography."""
    book = get_object_or_404(Book, pk=book_id)
    try:
        ub = UserBook.objects.get(user=request.user, book=book)
        user_shelf = ub.shelf
        user_rating = ub.rating
        user_review = ub.review
    except UserBook.DoesNotExist:
        user_shelf = ""
        user_rating = 0
        user_review = ""

    # Community reviews (everyone except the current user, most recent first).
    community = (
        UserBook.objects
        .filter(book=book)
        .exclude(user=request.user)
        .exclude(rating=0, review="")
        .select_related("user", "user__profile")
        .order_by("-updated_at")[:30]
    )
    reviews = []
    for r in community:
        reviews.append({
            "username": r.user.username,
            "display_name": r.user.profile.display_name,
            "initials": r.user.profile.initials,
            "avatar_a": r.user.profile.avatar_color_a,
            "avatar_b": r.user.profile.avatar_color_b,
            "rating": r.rating,
            "review": r.review,
            "shelf": r.shelf,
            "updated_at": r.updated_at.strftime("%b %d, %Y"),
        })

    # Star-distribution breakdown — for the Goodreads-style bar chart.
    rating_breakdown = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    rated_qs = UserBook.objects.filter(book=book).exclude(rating=0)
    for r in rated_qs.values("rating"):
        v = r["rating"]
        if v in rating_breakdown:
            rating_breakdown[v] += 1
    rated_count = sum(rating_breakdown.values())

    # Shelf counts so the modal can show "X read · Y reading · Z want".
    shelf_counts = {}
    for shelf_key, _label in UserBook.SHELF_CHOICES:
        shelf_counts[shelf_key] = UserBook.objects.filter(book=book, shelf=shelf_key).count()

    # Other books by the same author (in our catalog).
    other_by_author = (
        Book.objects
        .filter(author__iexact=book.author)
        .exclude(pk=book.pk)
        .order_by("-avg_rating")[:6]
    )
    more_books = [{
        "id": b.id,
        "title": b.title,
        "cover_url": b.cover_url,
        "cover_bg": b.cover_bg,
        "cover_color": b.cover_color,
        "avg_rating": b.avg_rating,
        "year": b.year,
    } for b in other_by_author]

    # Books-by-author count for the "About the author" section.
    author_book_count = Book.objects.filter(author__iexact=book.author).count()

    return JsonResponse({
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "genre": book.get_genre_display(),
        "avg_rating": book.avg_rating,
        "rated_count": rated_count,
        "review_count": rated_qs.exclude(review="").count(),
        "rating_breakdown": rating_breakdown,
        "pages": book.pages,
        "year": book.year,
        "description": book.description,
        "cover_bg": book.cover_bg,
        "cover_color": book.cover_color,
        "cover_url": book.cover_url,
        "source": book.source,
        "user_shelf": user_shelf,
        "user_rating": user_rating,
        "user_review": user_review,
        "reviews": reviews,
        "shelf_counts": shelf_counts,
        "more_by_author": more_books,
        "author_book_count": author_book_count,
    })


@login_required
@require_POST
def save_book(request, book_id):
    """Save shelf / rating / review for a book — used by the modal."""
    book = get_object_or_404(Book, pk=book_id)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    shelf = payload.get("shelf", "").strip().lower()
    shelf_map = {
        "reading": "reading",
        "read": "read",
        "want to read": "want",
        "want": "want",
        "favorites": "favorites",
    }
    shelf_key = shelf_map.get(shelf)

    rating = int(payload.get("rating", 0) or 0)
    rating = max(0, min(5, rating))
    review = (payload.get("review") or "").strip()

    # Verification gate: unverified users can shelve but can't post reviews.
    if review and _needs_verification(request.user):
        return JsonResponse(
            {"ok": False, "error": "Verify your email before posting reviews."},
            status=403,
        )

    # Profanity filter on review text
    if review:
        review = _profanity_filter(review)

    if not shelf_key and rating == 0 and not review:
        return JsonResponse({"ok": False, "error": "Nothing to save."}, status=400)

    ub, created = UserBook.objects.get_or_create(
        user=request.user,
        book=book,
        defaults={"shelf": shelf_key or "want"},
    )
    previous_shelf = ub.shelf
    if shelf_key:
        ub.shelf = shelf_key
    if rating:
        ub.rating = rating
    if review:
        ub.review = review
    ub.save()

    # Keep the book's cached average rating in sync.
    if rating:
        book.refresh_avg_rating()

    # Generate an activity entry on meaningful events
    action = None
    if shelf_key == "reading" and (created or previous_shelf != "reading"):
        action = "started"
    elif shelf_key == "read" and (created or previous_shelf != "read"):
        action = "finished" if not rating else "rated"
    elif shelf_key == "want" and created:
        action = "wantlisted"
    elif shelf_key == "favorites" and (created or previous_shelf != "favorites"):
        action = "favorited"
    elif rating and not shelf_key:
        action = "rated"

    if action:
        Activity.objects.create(
            user=request.user,
            book=book,
            action=action,
            stars=rating,
            review=review,
        )

    # Log a daily-activity tick for the streak/heatmap.
    _log_activity(request.user)

    return JsonResponse({"ok": True, "message": f'"{book.title}" saved to your shelf.'})


@login_required
@require_POST
def remove_from_shelf(request, ub_id):
    ub = get_object_or_404(UserBook, pk=ub_id, user=request.user)
    title = ub.book.title
    ub.delete()
    messages.success(request, f'Removed "{title}" from your shelf.')
    return redirect(request.META.get("HTTP_REFERER", "books:shelves"))


@login_required
@require_POST
def set_goal(request):
    try:
        goal = int(request.POST.get("goal", 20))
    except ValueError:
        return HttpResponseBadRequest("Goal must be an integer.")
    goal = max(1, min(500, goal))
    challenge = _get_or_create_challenge(request.user)
    challenge.goal = goal
    challenge.save()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "goal": goal})
    return redirect("books:challenge")


@login_required
@require_POST
def mark_notif_read(request, notif_id):
    notif = get_object_or_404(Notification, pk=notif_id, user=request.user)
    notif.is_read = True
    notif.save(update_fields=["is_read"])
    return JsonResponse({"ok": True})


@login_required
@require_POST
def send_friend_request(request, user_id):
    """Send a friend request to another user. Requires email verification when
    the feature flag is on, and is rate-limited per hour."""
    from django.conf import settings

    target = get_object_or_404(User, pk=user_id)
    if target == request.user:
        return JsonResponse({"ok": False, "error": "You can't friend yourself."}, status=400)
    if _needs_verification(request.user):
        return JsonResponse(
            {"ok": False, "error": "Verify your email before sending friend requests."},
            status=403,
        )

    # Already friends?
    if Friendship.objects.filter(user=request.user, friend=target).exists():
        return JsonResponse({"ok": True, "status": "already_friends"})

    # Existing pending request from current user?
    if FriendRequest.objects.filter(
        sender=request.user, receiver=target, status="pending"
    ).exists():
        return JsonResponse({"ok": True, "status": "already_pending"})

    # Counter-request: target already asked us → accept it instead of opening new.
    counter = FriendRequest.objects.filter(
        sender=target, receiver=request.user, status="pending"
    ).first()
    if counter:
        return _accept_friend_request(request.user, counter)

    # Rate limit
    limit = settings.FRIEND_REQUEST_RATE_LIMIT_PER_HOUR
    if _hourly_friend_request_count(request.user) >= limit:
        return JsonResponse(
            {"ok": False, "error": f"Friend request limit reached ({limit}/hour). Try again later."},
            status=429,
        )

    FriendRequest.objects.create(sender=request.user, receiver=target)
    Notification.objects.create(
        user=target,
        icon="ti-user-plus",
        text=f"{request.user.profile.display_name} sent you a friend request.",
    )
    return JsonResponse({"ok": True, "status": "pending"})


def _accept_friend_request(user, fr: FriendRequest):
    """Shared accept logic — used by the explicit accept endpoint and the
    counter-request shortcut in send_friend_request."""
    fr.status = "accepted"
    fr.responded_at = timezone.now()
    fr.save(update_fields=["status", "responded_at"])
    # Create the symmetric Friendship rows (idempotent).
    Friendship.objects.get_or_create(user=fr.sender, friend=fr.receiver, defaults={"request": fr})
    Friendship.objects.get_or_create(user=fr.receiver, friend=fr.sender, defaults={"request": fr})
    Notification.objects.create(
        user=fr.sender,
        icon="ti-user-check",
        text=f"{fr.receiver.profile.display_name} accepted your friend request.",
    )
    return JsonResponse({"ok": True, "status": "friends"})


@login_required
@require_POST
def respond_friend_request(request, req_id):
    """Accept or decline a pending friend request addressed to the current user."""
    fr = get_object_or_404(FriendRequest, pk=req_id, receiver=request.user, status="pending")
    decision = (request.POST.get("decision") or "").strip().lower()
    if decision == "accept":
        return _accept_friend_request(request.user, fr)
    if decision == "decline":
        fr.status = "declined"
        fr.responded_at = timezone.now()
        fr.save(update_fields=["status", "responded_at"])
        return JsonResponse({"ok": True, "status": "declined"})
    return HttpResponseBadRequest("decision must be 'accept' or 'decline'.")


@login_required
@require_POST
def unfriend(request, user_id):
    """Remove an existing friendship in both directions."""
    target = get_object_or_404(User, pk=user_id)
    Friendship.objects.filter(user=request.user, friend=target).delete()
    Friendship.objects.filter(user=target, friend=request.user).delete()
    return JsonResponse({"ok": True, "status": "removed"})


@login_required
@require_POST
def update_progress(request, ub_id):
    ub = get_object_or_404(UserBook, pk=ub_id, user=request.user)
    # Accept either JSON body or form-encoded POST data.
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")
    else:
        payload = request.POST
    try:
        progress = int(payload.get("progress", ub.progress))
        page = int(payload.get("page", payload.get("current_page", ub.current_page)))
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid numbers.")
    ub.progress = max(0, min(100, progress))
    ub.current_page = max(0, page)
    if ub.progress >= 100 and ub.shelf == "reading":
        ub.shelf = "read"
        Activity.objects.create(user=request.user, book=ub.book, action="finished")
    ub.save()
    _log_activity(request.user)
    return JsonResponse({"ok": True, "progress": ub.progress, "shelf": ub.shelf})


@login_required
def streak_data(request):
    """Return the heatmap data (last 365 days) + current streak for the user
    whose username is given, or the current user if none."""
    from .models import DailyActivity
    username = request.GET.get("user", "").strip()
    if username:
        target = get_object_or_404(User, username=username)
    else:
        target = request.user

    today = timezone.localdate()
    start = today - datetime.timedelta(days=364)
    rows = DailyActivity.objects.filter(user=target, date__gte=start)
    by_date = {r.date.isoformat(): r.actions for r in rows}

    days = []
    for i in range(365):
        d = start + datetime.timedelta(days=i)
        iso = d.isoformat()
        days.append({"date": iso, "count": by_date.get(iso, 0)})

    return JsonResponse({
        "ok": True,
        "current_streak": _current_streak(target),
        "total_active_days": len(by_date),
        "days": days,
    })


@login_required
def search(request):
    """Simple search endpoint — returns redirect to discover with query."""
    q = request.GET.get("q", "").strip()
    return redirect(f"/discover/?q={q}" if q else "books:discover")


@login_required
@require_POST
def import_book(request):
    """Import a book from any supported provider and return its local id.
    Called when the user clicks a remote search result."""
    from . import services

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    volume_id = (payload.get("volume_id") or payload.get("external_id") or "").strip()
    source = (payload.get("source") or "").strip().lower()
    if not volume_id:
        return JsonResponse({"ok": False, "error": "volume_id required."}, status=400)

    book = services.import_book(volume_id, source=source)
    if not book:
        return JsonResponse(
            {"ok": False, "error": "Could not import that book — the source API didn't respond."},
            status=502,
        )
    return JsonResponse({
        "ok": True,
        "book": {"id": book.id, "title": book.title, "author": book.author},
    })


@login_required
@require_POST
def report_content(request):
    """File a moderation report. Body: {target_type, target_id, reason, detail}."""
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    target_type = (payload.get("target_type") or "").strip().lower()
    if target_type not in {"review", "user", "book"}:
        return JsonResponse({"ok": False, "error": "Invalid target_type."}, status=400)

    try:
        target_id = int(payload.get("target_id") or 0)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid target_id."}, status=400)
    if target_id <= 0:
        return JsonResponse({"ok": False, "error": "Invalid target_id."}, status=400)

    reason = (payload.get("reason") or "other").strip().lower()
    valid_reasons = {r[0] for r in Report.REASON_CHOICES}
    if reason not in valid_reasons:
        reason = "other"

    Report.objects.create(
        reporter=request.user,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        detail=(payload.get("detail") or "")[:1000],
    )
    return JsonResponse({"ok": True, "message": "Report submitted. Thanks — our team will review it."})


@login_required
def author_detail(request, name):
    """Return JSON with the author's bio + the books we have by them.
    Used by the 'click an author name' interaction."""
    from .services.authors import lookup_author
    import urllib.parse

    name = urllib.parse.unquote(name)
    info = lookup_author(name) or {}

    books = Book.objects.filter(author__iexact=name).order_by("-avg_rating")[:12]
    catalog_books = [{
        "id": b.id, "title": b.title, "cover_url": b.cover_url,
        "cover_bg": b.cover_bg, "cover_color": b.cover_color,
        "avg_rating": b.avg_rating, "year": b.year,
    } for b in books]

    return JsonResponse({
        "ok": True,
        "author": {
            "name": info.get("name") or name,
            "bio": info.get("bio") or "",
            "photo_url": info.get("photo_url") or "",
            "work_count": info.get("work_count") or 0,
            "top_subjects": info.get("top_subjects") or [],
            "birth_date": info.get("birth_date") or "",
        },
        "books_in_catalog": catalog_books,
    })


# ---------------------------------------------------------------------------
# Buddy Reads
# ---------------------------------------------------------------------------
@login_required
def buddy_reads(request):
    """List all of the user's buddy reads (incoming invites, active, done)."""
    from .models import BuddyRead
    user = request.user
    mine = BuddyRead.objects.filter(
        Q(initiator=user) | Q(partner=user)
    ).select_related("book", "initiator", "partner",
                     "initiator__profile", "partner__profile")

    incoming = [br for br in mine if br.partner_id == user.id and br.status == "pending"]
    active = [br for br in mine if br.status == "active"]
    pending_sent = [br for br in mine if br.initiator_id == user.id and br.status == "pending"]
    finished = [br for br in mine if br.status in ("completed", "abandoned", "declined")]

    # Annotate each with the other user + progress for display
    def decorate(br):
        other = br.other_user(user)
        my_ub = UserBook.objects.filter(user=user, book=br.book).first()
        other_ub = UserBook.objects.filter(user=other, book=br.book).first()
        return {
            "br": br,
            "other": other,
            "my_progress": my_ub.progress if my_ub else 0,
            "other_progress": other_ub.progress if other_ub else 0,
        }

    return render(request, "books/buddy_reads.html", {
        "active_page": "buddy",
        "incoming": [decorate(br) for br in incoming],
        "active_reads": [decorate(br) for br in active],
        "pending_sent": [decorate(br) for br in pending_sent],
        "finished": [decorate(br) for br in finished],
    })


@login_required
@require_POST
def buddy_invite(request):
    """Invite a friend to a buddy read. Body: {book_id, partner_id}."""
    from .models import BuddyRead
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    book = get_object_or_404(Book, pk=payload.get("book_id"))
    partner = get_object_or_404(User, pk=payload.get("partner_id"))
    if partner == request.user:
        return JsonResponse({"ok": False, "error": "You can't buddy read with yourself."}, status=400)

    # Don't duplicate an existing open buddy read for the same book+pair.
    existing = BuddyRead.objects.filter(
        book=book, status__in=["pending", "active"],
    ).filter(
        Q(initiator=request.user, partner=partner) | Q(initiator=partner, partner=request.user)
    ).first()
    if existing:
        return JsonResponse({"ok": True, "status": existing.status, "id": existing.id})

    br = BuddyRead.objects.create(book=book, initiator=request.user, partner=partner)
    Notification.objects.create(
        user=partner,
        icon="ti-users",
        text=f"{request.user.profile.display_name} invited you to buddy read \"{book.title}\".",
    )
    return JsonResponse({"ok": True, "status": "pending", "id": br.id})


@login_required
@require_POST
def buddy_respond(request, br_id):
    """Accept or decline a buddy read invite. Body: {decision: accept|decline}."""
    from .models import BuddyRead
    br = get_object_or_404(BuddyRead, pk=br_id, partner=request.user, status="pending")
    decision = (request.POST.get("decision") or "").strip().lower()
    if decision == "accept":
        br.status = "active"
        br.save(update_fields=["status", "updated_at"])
        Notification.objects.create(
            user=br.initiator, icon="ti-users",
            text=f"{request.user.profile.display_name} accepted your buddy read of \"{br.book.title}\"!",
        )
        return JsonResponse({"ok": True, "status": "active"})
    if decision == "decline":
        br.status = "declined"
        br.save(update_fields=["status", "updated_at"])
        return JsonResponse({"ok": True, "status": "declined"})
    return HttpResponseBadRequest("decision must be accept or decline.")


@login_required
def buddy_detail(request, br_id):
    """The buddy read thread page with progress + spoiler-gated messages."""
    from .models import BuddyRead
    br = get_object_or_404(
        BuddyRead.objects.select_related("book", "initiator", "partner"),
        pk=br_id,
    )
    if request.user not in (br.initiator, br.partner):
        return redirect("books:buddy_reads")

    other = br.other_user(request.user)
    my_ub = UserBook.objects.filter(user=request.user, book=br.book).first()
    other_ub = UserBook.objects.filter(user=other, book=br.book).first()
    my_page = my_ub.current_page if my_ub else 0

    messages_qs = br.messages.select_related("author", "author__profile")
    msgs = []
    for m in messages_qs:
        # Spoiler gate: hide a message from the *other* reader until they
        # reach its page marker. Your own messages are always visible.
        gated = (
            m.author_id != request.user.id
            and m.page_marker > 0
            and my_page < m.page_marker
        )
        msgs.append({"m": m, "gated": gated})

    return render(request, "books/buddy_detail.html", {
        "active_page": "buddy",
        "br": br,
        "other": other,
        "my_progress": my_ub.progress if my_ub else 0,
        "other_progress": other_ub.progress if other_ub else 0,
        "my_page": my_page,
        "messages": msgs,
    })


@login_required
@require_POST
def buddy_post_message(request, br_id):
    """Post a message to a buddy read thread."""
    from .models import BuddyRead, BuddyReadMessage
    br = get_object_or_404(BuddyRead, pk=br_id)
    if request.user not in (br.initiator, br.partner):
        return JsonResponse({"ok": False, "error": "Not your buddy read."}, status=403)

    text = (request.POST.get("text") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "Message can't be empty."}, status=400)
    try:
        page_marker = int(request.POST.get("page_marker") or 0)
    except (TypeError, ValueError):
        page_marker = 0

    BuddyReadMessage.objects.create(
        buddy_read=br, author=request.user, text=_profanity_filter(text),
        page_marker=max(0, page_marker),
    )
    # Notify the other person
    other = br.other_user(request.user)
    Notification.objects.create(
        user=other, icon="ti-message-circle",
        text=f"{request.user.profile.display_name} posted in your buddy read of \"{br.book.title}\".",
    )
    _log_activity(request.user)
    return redirect("books:buddy_detail", br_id=br.id)


@login_required
def buddy_candidates(request, book_id):
    """Return the user's friends who could be invited to buddy read this book."""
    from .models import BuddyRead
    book = get_object_or_404(Book, pk=book_id)
    friends = _friend_users(request.user)
    # Exclude friends already in an open buddy read for this book with the user
    busy = set(
        BuddyRead.objects.filter(book=book, status__in=["pending", "active"])
        .filter(Q(initiator=request.user) | Q(partner=request.user))
        .values_list("initiator_id", "partner_id")
    )
    busy_ids = {i for pair in busy for i in pair}
    out = [{
        "id": f.id,
        "name": f.profile.display_name,
        "initials": f.profile.initials,
        "avatar_a": f.profile.avatar_color_a,
        "avatar_b": f.profile.avatar_color_b,
    } for f in friends if f.id not in busy_ids]
    return JsonResponse({"ok": True, "friends": out})
