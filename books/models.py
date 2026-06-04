from django.conf import settings
from django.db import models
from django.utils import timezone


class Book(models.Model):
    """Canonical book record. Books are not user-editable — they are sourced from
    trusted external APIs (Google Books, Open Library) and de-duplicated by the
    provider's stable identifier. Seed data is the only exception, kept for
    development convenience."""

    GENRE_CHOICES = [
        ("fantasy", "Fantasy"),
        ("scifi", "Sci-Fi"),
        ("mystery", "Mystery"),
        ("literary", "Literary Fiction"),
        ("nonfiction", "Non-Fiction"),
        ("romance", "Romance"),
    ]

    SOURCE_CHOICES = [
        ("google", "Google Books"),
        ("openlibrary", "Open Library"),
        ("seed", "Seed data (development)"),
    ]

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=120)
    genre = models.CharField(max_length=20, choices=GENRE_CHOICES, default="literary")
    avg_rating = models.FloatField(default=0.0)
    pages = models.PositiveIntegerField(default=0)
    year = models.PositiveIntegerField(default=2024)
    description = models.TextField(blank=True, default="")
    # Visual: deterministic cover background and accent colour
    cover_bg = models.CharField(max_length=7, default="#2D4A3E")
    cover_color = models.CharField(max_length=7, default="#A8C9B8")
    # API provenance — prevents duplicate records and proves the book came from
    # a trusted external source.
    isbn = models.CharField(max_length=20, blank=True, default="", db_index=True)
    external_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True,
        help_text="Provider's stable id (e.g. Google Books volume id)",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="seed")
    cover_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="unique_book_per_provider",
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"

    def refresh_avg_rating(self):
        """Recompute the cached avg_rating from current UserBook rows."""
        rated = self.user_books.exclude(rating=0)
        if rated.exists():
            total = sum(ub.rating for ub in rated)
            self.avg_rating = round(total / rated.count(), 2)
        else:
            self.avg_rating = 0.0
        self.save(update_fields=["avg_rating"])


class UserBook(models.Model):
    """A user's relationship with a book — which shelf, progress, rating, review."""

    SHELF_CHOICES = [
        ("reading", "Reading"),
        ("read", "Read"),
        ("want", "Want to Read"),
        ("favorites", "Favorites"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_books"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="user_books")
    shelf = models.CharField(max_length=20, choices=SHELF_CHOICES, default="want")
    progress = models.PositiveIntegerField(default=0, help_text="Percent (0–100)")
    current_page = models.PositiveIntegerField(default=0)
    rating = models.PositiveSmallIntegerField(default=0, help_text="0–5; 0 means unrated")
    review = models.TextField(blank=True, default="")
    added_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "book")
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} · {self.book.title} ({self.shelf})"


class FriendRequest(models.Model):
    """Pending / accepted / declined friend request between two verified users.
    Mutual approval is required — a Friendship row is only created when the
    receiver explicitly accepts."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
    ]

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_friend_requests"
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_friend_requests"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Only one open request per (sender, receiver) at a time.
            models.UniqueConstraint(
                fields=["sender", "receiver"],
                condition=models.Q(status="pending"),
                name="unique_pending_friend_request",
            ),
        ]

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username} ({self.status})"


class Friendship(models.Model):
    """A confirmed friendship. Stored as a directed row but always created in
    pairs (A→B and B→A) when a FriendRequest is accepted. Both rows reference
    the same originating FriendRequest so the relationship is auditable."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following"
    )
    friend = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="followers"
    )
    request = models.ForeignKey(
        FriendRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="friendships"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "friend")

    def __str__(self):
        return f"{self.user.username} <-> {self.friend.username}"


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    icon = models.CharField(max_length=40, default="ti-bell")
    text = models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notif<{self.user.username}: {self.text[:30]}>"


class ReadingChallenge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="challenges"
    )
    year = models.PositiveIntegerField()
    goal = models.PositiveIntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "year")
        ordering = ["-year"]

    def __str__(self):
        return f"{self.user.username} · {self.year} goal {self.goal}"


class Activity(models.Model):
    """Feed item — generated when a user does something noteworthy."""

    ACTIONS = [
        ("rated", "rated and reviewed"),
        ("finished", "finished reading"),
        ("started", "started reading"),
        ("wantlisted", "added to Want to Read"),
        ("favorited", "added to Favorites"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="activities"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="activities")
    action = models.CharField(max_length=20, choices=ACTIONS)
    stars = models.PositiveSmallIntegerField(default=0)
    review = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Activities"

    def get_action_display_text(self):
        return dict(self.ACTIONS).get(self.action, self.action)


class Report(models.Model):
    """User-submitted moderation report. Reviewed by staff in the admin."""

    TARGET_CHOICES = [
        ("review", "Review"),
        ("user", "User"),
        ("book", "Book"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]
    REASON_CHOICES = [
        ("spam", "Spam"),
        ("harassment", "Harassment / abuse"),
        ("inappropriate", "Inappropriate content"),
        ("fake", "Fake / misleading"),
        ("other", "Other"),
    ]

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_filed"
    )
    target_type = models.CharField(max_length=10, choices=TARGET_CHOICES)
    # Generic FK by id — we keep this simple to avoid contenttypes ceremony.
    target_id = models.PositiveIntegerField()
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="other")
    detail = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reports_resolved",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Report<{self.target_type}#{self.target_id} by {self.reporter.username} - {self.status}>"


class DailyActivity(models.Model):
    """One row per user per day they took *any* book-related action.
    Powers the GitHub-style heatmap and the daily reading streak counter."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_activity"
    )
    date = models.DateField()
    actions = models.PositiveIntegerField(default=1)  # incremented on each action that day

    class Meta:
        unique_together = ("user", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"DailyActivity<{self.user.username} {self.date}>"


class BuddyRead(models.Model):
    """Two users reading the same book together, with a shared discussion
    thread. The defining social feature that sets PageTurner apart."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("declined", "Declined"),
        ("abandoned", "Abandoned"),
    ]

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="buddy_reads")
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buddy_initiated"
    )
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buddy_joined"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    target_finish_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"BuddyRead<{self.book.title}: {self.initiator.username} & {self.partner.username}>"

    def other_user(self, user):
        return self.partner if user == self.initiator else self.initiator


class BuddyReadMessage(models.Model):
    """A message in a buddy read thread. `page_marker` enables the spoiler
    gate: a message tagged 'page 200' stays blurred for the partner until
    they've passed page 200 themselves."""

    buddy_read = models.ForeignKey(
        BuddyRead, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buddy_messages"
    )
    page_marker = models.PositiveIntegerField(
        default=0, help_text="Hide from partner until they reach this page (0 = no spoiler)"
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Msg<{self.author.username} in {self.buddy_read_id}>"
