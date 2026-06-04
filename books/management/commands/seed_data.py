"""
Usage:
    python manage.py seed_data           # seed if empty
    python manage.py seed_data --reset   # wipe & re-seed
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from books.models import (
    Activity,
    Book,
    Friendship,
    Notification,
    ReadingChallenge,
    UserBook,
)

COVERS = [
    ("#2D4A3E", "#A8C9B8"),
    ("#4A2D35", "#C9A8B0"),
    ("#2D3A4A", "#A8B5C9"),
    ("#4A3D2D", "#C9B8A8"),
    ("#3A2D4A", "#B8A8C9"),
    ("#2D4A2D", "#A8C9A8"),
    ("#4A4A2D", "#C9C9A8"),
    ("#3D2D2D", "#C9B0A8"),
    ("#2D3D2D", "#A8C4A8"),
    ("#3D3D4A", "#B8B8C9"),
]

BOOKS = [
    ("The Name of the Wind", "Patrick Rothfuss", "fantasy", 4.5, 662, 2007,
     "A young man grows to be the most notorious wizard his world has ever seen, narrating his life story to a chronicler."),
    ("Project Hail Mary", "Andy Weir", "scifi", 4.8, 476, 2021,
     "A lone astronaut must save Earth from an extinction-level threat. An instant classic of hard science fiction."),
    ("Rebecca", "Daphne du Maurier", "mystery", 4.3, 449, 1938,
     "A classic gothic mystery where a shy young woman marries a widower and moves into his imposing estate."),
    ("Normal People", "Sally Rooney", "literary", 3.9, 273, 2018,
     "A story of two people and how love can fundamentally alter who you are and how you live your life."),
    ("Sapiens", "Yuval Noah Harari", "nonfiction", 4.4, 443, 2011,
     "A brief history of humankind from the Stone Age to the present, exploring how Homo sapiens came to dominate the planet."),
    ("The Midnight Library", "Matt Haig", "literary", 3.9, 288, 2020,
     "A library between life and death where each book represents a different life you could have lived."),
    ("Dune", "Frank Herbert", "scifi", 4.6, 896, 1965,
     "A sweeping epic of politics, religion, and ecology set on the desert planet Arrakis."),
    ("The Thursday Murder Club", "Richard Osman", "mystery", 4.1, 382, 2020,
     "Four unlikely friends in a retirement village solve cold cases — until a real murder occurs on their doorstep."),
    ("The Way of Kings", "Brandon Sanderson", "fantasy", 4.6, 1007, 2010,
     "Epic fantasy set on a world swept by devastating storms, where legends and destiny collide."),
    ("Lessons in Chemistry", "Bonnie Garmus", "literary", 4.2, 389, 2022,
     "A chemist who becomes a cooking show host in the 1960s uses science to empower housewives."),
    ("The Long Game", "Elena Moore", "romance", 4.0, 312, 2023,
     "Two rivals at a prestigious firm discover that competing and falling in love might not be mutually exclusive."),
    ("Klara and the Sun", "Kazuo Ishiguro", "scifi", 3.8, 307, 2021,
     "Told through the eyes of an Artificial Friend, a moving meditation on love, memory, and what it means to be human."),
    ("A Little Life", "Hanya Yanagihara", "literary", 4.2, 720, 2015,
     "Four friends navigate life, friendship, and trauma across decades of their lives in New York City."),
    ("The Atlas Six", "Olivie Blake", "fantasy", 3.7, 393, 2020,
     "Six talented young magicians are recruited into a secret society, but only five will be initiated."),
    ("Educated", "Tara Westover", "nonfiction", 4.5, 334, 2018,
     "A memoir of a young woman who grows up in a survivalist family and educates herself to earn a PhD at Cambridge."),
    ("The House in the Cerulean Sea", "TJ Klune", "fantasy", 4.3, 394, 2020,
     "A love story about the misfit magical children in a remote orphanage and the caseworker sent to evaluate them."),
]

DEMO_USERS = [
    ("aria", "Aria", "Chen", "aria@example.com"),
    ("marcus", "Marcus", "Webb", "marcus@example.com"),
    ("priya", "Priya", "Nair", "priya@example.com"),
    ("sam", "Sam", "Torres", "sam@example.com"),
    ("lena", "Lena", "Hofmann", "lena@example.com"),
    ("diego", "Diego", "Park", "diego@example.com"),
]

DEMO_PASSWORD = "readwell123"


class Command(BaseCommand):
    help = "Seed the database with books, demo users, friendships and activity."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Wipe before seeding")

    def handle(self, *args, **opts):
        if opts["reset"]:
            self.stdout.write(self.style.WARNING("Wiping data..."))
            from books.models import FriendRequest as _FR, Report as _RP
            Activity.objects.all().delete()
            Notification.objects.all().delete()
            _RP.objects.all().delete()
            _FR.objects.all().delete()
            Friendship.objects.all().delete()
            UserBook.objects.all().delete()
            ReadingChallenge.objects.all().delete()
            Book.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()

        # Books — try real sources (Google Books → Open Library fallback) first,
        # fall back to local definitions only if both APIs are unreachable. Real
        # books are strongly preferred so the catalog never contains fabricated
        # entries on a normal install.
        if Book.objects.exists() and not opts["reset"]:
            self.stdout.write(self.style.NOTICE("Books already seeded; skipping."))
        else:
            from books import services

            self.stdout.write("Importing real books from Google Books / Open Library...")
            real_count = 0
            popular_queries = [
                "Project Hail Mary Andy Weir",
                "Mistborn Brandon Sanderson",
                "The Hunger Games Suzanne Collins",
                "Where the Crawdads Sing Delia Owens",
                "The Seven Husbands of Evelyn Hugo",
                "Tomorrow and Tomorrow and Tomorrow Zevin",
                "Pachinko Min Jin Lee",
                "A Little Life Yanagihara",
                "Dune Frank Herbert",
                "The Midnight Library Matt Haig",
                "Klara and the Sun Ishiguro",
                "Atomic Habits James Clear",
                "Educated Tara Westover",
                "Sapiens Yuval Harari",
                "Circe Madeline Miller",
                "The Silent Patient Michaelides",
            ]
            for q in popular_queries:
                results = services.book_search(q, max_results=1)
                if results:
                    vid = results[0].get("external_id")
                    src = results[0].get("source")
                    if vid and services.import_book(vid, source=src):
                        real_count += 1

            if real_count >= 8:
                self.stdout.write(self.style.SUCCESS(
                    f"Imported {real_count} real books from open APIs."
                ))
            else:
                # Both APIs failed — fall back to local definitions so dev
                # environments without internet still have a usable demo.
                self.stdout.write(self.style.WARNING(
                    f"\n  Only {real_count} real books imported — both Google Books and "
                    f"Open Library are unreachable from this machine."
                ))
                self.stdout.write(self.style.WARNING(
                    "  Falling back to local demo data. This is for OFFLINE DEV ONLY — "
                    "for a real catalog, run:"
                ))
                self.stdout.write(self.style.WARNING(
                    "      python manage.py import_popular_books --replace\n"
                ))
                for i, (title, author, genre, rating, pages, year, desc) in enumerate(BOOKS):
                    bg, color = COVERS[i % len(COVERS)]
                    Book.objects.get_or_create(
                        title=title, author=author,
                        defaults=dict(
                            genre=genre, avg_rating=rating, pages=pages, year=year,
                            description=desc, cover_bg=bg, cover_color=color, source="seed",
                        ),
                    )
                self.stdout.write(self.style.SUCCESS(f"Created {len(BOOKS)} fallback demo books."))

        # Demo users
        self.stdout.write("Seeding demo users...")
        users = {}
        for username, first, last, email in DEMO_USERS:
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "email": email},
            )
            if created:
                u.set_password(DEMO_PASSWORD)
                u.save()
            users[username] = u

        # Demo user "jamie" matches the original mock UI
        jamie, created = User.objects.get_or_create(
            username="jamie",
            defaults={"first_name": "Jamie", "last_name": "Reynolds", "email": "jamie@example.com"},
        )
        if created:
            jamie.set_password(DEMO_PASSWORD)
            jamie.save()
            self.stdout.write(self.style.SUCCESS(
                f"Created demo account jamie / {DEMO_PASSWORD}"
            ))
        users["jamie"] = jamie

        # Profile location for jamie
        jp = jamie.profile
        jp.location = "San Francisco"
        jp.save(update_fields=["location"])

        all_books = list(Book.objects.all())
        if not all_books:
            return

        # Shelves for jamie — match the original mock
        self.stdout.write("Building jamie's shelves...")
        reading_titles = ["Project Hail Mary", "The Way of Kings"]
        read_titles = [
            "The Name of the Wind", "Rebecca", "Normal People", "Sapiens",
            "The Midnight Library", "Dune", "Lessons in Chemistry",
            "A Little Life", "Educated", "The House in the Cerulean Sea",
            "The Thursday Murder Club", "The Long Game", "The Atlas Six",
        ]
        want_titles = ["The Long Game", "Klara and the Sun", "The Atlas Six"]
        fav_titles = ["The Name of the Wind", "Dune", "The Way of Kings",
                      "A Little Life", "Educated"]

        def book(t): return next((b for b in all_books if b.title == t), None)

        for t in reading_titles:
            b = book(t)
            if b:
                UserBook.objects.update_or_create(
                    user=jamie, book=b,
                    defaults={"shelf": "reading",
                              "progress": random.choice([28, 45, 63]),
                              "current_page": random.randint(120, b.pages - 50)},
                )
        for t in read_titles:
            b = book(t)
            if b:
                UserBook.objects.update_or_create(
                    user=jamie, book=b,
                    defaults={"shelf": "read",
                              "rating": random.choice([4, 5, 4, 5, 3]),
                              "progress": 100,
                              "current_page": b.pages},
                )
        for t in want_titles:
            b = book(t)
            if b:
                UserBook.objects.update_or_create(
                    user=jamie, book=b,
                    defaults={"shelf": "want"},
                )
        # Favorites: mark some read books as favorites (re-shelf, since unique together)
        # Use a side flag by re-tagging shelf for those specifically
        for t in fav_titles:
            b = book(t)
            if b:
                UserBook.objects.update_or_create(
                    user=jamie, book=b,
                    defaults={"shelf": "favorites", "rating": 5, "progress": 100,
                              "current_page": b.pages},
                )

        # Sprinkle some shelves on demo users so feed/friends are interesting
        for u in users.values():
            if u == jamie:
                continue
            picks = random.sample(all_books, k=min(5, len(all_books)))
            for b in picks:
                shelf = random.choice(["read", "read", "reading", "want"])
                UserBook.objects.update_or_create(
                    user=u, book=b,
                    defaults={"shelf": shelf,
                              "rating": random.choice([0, 4, 5]) if shelf == "read" else 0,
                              "progress": 100 if shelf == "read" else random.randint(10, 80)},
                )

        # Friendships — jamie is friends with everyone via accepted FriendRequests.
        # We seed the FriendRequest history too so the moderation audit trail looks real.
        self.stdout.write("Building friendships...")
        from books.models import FriendRequest
        from django.utils import timezone as _tz
        for u in users.values():
            if u != jamie:
                fr, _ = FriendRequest.objects.get_or_create(
                    sender=u, receiver=jamie,
                    defaults={"status": "accepted", "responded_at": _tz.now()},
                )
                if fr.status != "accepted":
                    fr.status = "accepted"
                    fr.responded_at = _tz.now()
                    fr.save(update_fields=["status", "responded_at"])
                Friendship.objects.get_or_create(user=jamie, friend=u, defaults={"request": fr})
                Friendship.objects.get_or_create(user=u, friend=jamie, defaults={"request": fr})

        # Mark every demo profile as email-verified so the verification flag
        # doesn't block their actions if it's turned on.
        for u in users.values():
            profile = u.profile
            if not profile.is_email_verified:
                profile.is_email_verified = True
                profile.save(update_fields=["is_email_verified"])

        # Activity feed — recent events from friends
        self.stdout.write("Building activity feed...")
        Activity.objects.filter(user__in=[u for u in users.values() if u != jamie]).delete()
        feed_items = [
            ("aria", "rated", "Dune", 5,
             "An absolute masterpiece of science fiction. The world-building is unmatched and the political intrigue kept me hooked till the very last page.", 2),
            ("marcus", "finished", "Sapiens", 4,
             "Fascinating overview of human history. Sometimes overgeneralises but the core ideas are compelling and thought-provoking.", 5),
            ("priya", "wantlisted", "Klara and the Sun", 0, "", 8),
            ("sam", "started", "Rebecca", 0, "", 24),
            ("lena", "rated", "Lessons in Chemistry", 5,
             "Hilarious, warm, and surprisingly moving. Elizabeth Zott is one of the best characters I have ever read.", 26),
            ("diego", "started", "The Atlas Six", 0, "", 30),
        ]
        now = timezone.now()
        for username, action, title, stars, review, hours_ago in feed_items:
            u = users.get(username)
            b = book(title)
            if not u or not b:
                continue
            a = Activity.objects.create(
                user=u, book=b, action=action, stars=stars, review=review,
            )
            Activity.objects.filter(pk=a.pk).update(
                created_at=now - timedelta(hours=hours_ago),
            )

        # Notifications for jamie
        self.stdout.write("Building notifications...")
        Notification.objects.filter(user=jamie).delete()
        notifs = [
            ("ti-star", "Aria Chen rated The Name of the Wind — 5 stars", False, 2),
            ("ti-message", "Marcus Webb commented on your review of Sapiens", False, 4),
            ("ti-trophy", "You are 65% through your reading challenge!", False, 24),
            ("ti-user-plus", "Lena Hofmann started following you", True, 48),
            ("ti-book", "New release from Brandon Sanderson is now available", True, 72),
        ]
        for icon, text, is_read, hours_ago in notifs:
            n = Notification.objects.create(
                user=jamie, icon=icon, text=text, is_read=is_read,
            )
            Notification.objects.filter(pk=n.pk).update(
                created_at=now - timedelta(hours=hours_ago),
            )

        # Challenge for jamie
        ReadingChallenge.objects.update_or_create(
            user=jamie, year=now.year, defaults={"goal": 20},
        )

        self.stdout.write(self.style.SUCCESS(
            "\nDone! Demo accounts (password: %s):" % DEMO_PASSWORD
        ))
        for u in users.values():
            self.stdout.write(f"  · {u.username}  ({u.get_full_name()})")
        self.stdout.write(self.style.SUCCESS(
            "\nLog in as 'jamie' to see a fully populated dashboard."
        ))
