"""Bootstrap the local catalog with real books pulled from Google Books.

Unlike seed_data, this command does not invent any book data. Each entry
is the result of a live Google Books search; the top match is imported via
the same code path real users hit when they click a remote search result.
If Google Books is unreachable we skip that title and report it — we never
fall back to fabricated data.

Usage:
    python manage.py import_popular_books            # add real books to catalog
    python manage.py import_popular_books --replace  # delete seed books first
"""
import time

from django.core.management.base import BaseCommand

from books import services
from books.models import Book


# Curated search queries. The first match for each is what gets imported,
# so we make the queries specific enough to land on the canonical edition.
POPULAR_QUERIES = [
    "Harry Potter and the Philosopher's Stone Rowling",
    "The Hunger Games Suzanne Collins",
    "Mistborn The Final Empire Sanderson",
    "Project Hail Mary Andy Weir",
    "Dune Frank Herbert",
    "The Name of the Wind Patrick Rothfuss",
    "Where the Crawdads Sing Delia Owens",
    "The Seven Husbands of Evelyn Hugo Taylor Jenkins Reid",
    "Tomorrow and Tomorrow and Tomorrow Gabrielle Zevin",
    "A Little Life Hanya Yanagihara",
    "The Midnight Library Matt Haig",
    "Klara and the Sun Kazuo Ishiguro",
    "The Thursday Murder Club Richard Osman",
    "Pachinko Min Jin Lee",
    "The Song of Achilles Madeline Miller",
    "Atomic Habits James Clear",
    "Educated Tara Westover",
    "Sapiens Yuval Noah Harari",
    "Circe Madeline Miller",
    "The Silent Patient Alex Michaelides",
]


class Command(BaseCommand):
    help = "Import real books from Google Books to populate the catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing seed-source books before importing.",
        )
        parser.add_argument(
            "--queries",
            nargs="*",
            help="Custom queries to import instead of the popular list.",
        )

    def handle(self, *args, **opts):
        queries = opts.get("queries") or POPULAR_QUERIES

        if opts["replace"]:
            count = Book.objects.filter(source="seed").count()
            if count:
                self.stdout.write(self.style.WARNING(
                    f"Deleting {count} seed books..."
                ))
                Book.objects.filter(source="seed").delete()

        self.stdout.write(f"Importing {len(queries)} books from Google Books...")
        imported = 0
        skipped = 0
        failed = 0

        for i, query in enumerate(queries, 1):
            results = services.book_search(query, max_results=3)
            if not results:
                self.stdout.write(self.style.WARNING(
                    f"  [{i}/{len(queries)}] {query!r}: no results from any source"
                ))
                failed += 1
                time.sleep(0.5)
                continue

            top = results[0]
            volume_id = top.get("external_id", "")
            source = top.get("source", "")
            if not volume_id:
                self.stdout.write(self.style.WARNING(
                    f"  [{i}/{len(queries)}] {query!r}: top match missing id"
                ))
                failed += 1
                continue

            # Already in the catalog?
            if Book.objects.filter(external_id=volume_id).exists():
                self.stdout.write(
                    f"  [{i}/{len(queries)}] {top['title']!r} — already imported"
                )
                skipped += 1
                continue

            book = services.import_book(volume_id, source=source)
            if book:
                provider = "Open Library" if book.source == "openlibrary" else "Google Books"
                self.stdout.write(self.style.SUCCESS(
                    f"  [{i}/{len(queries)}] {book.title!r} by {book.author}  ({provider})"
                ))
                imported += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f"  [{i}/{len(queries)}] {query!r}: fetch failed"
                ))
                failed += 1

            # Be polite to the APIs.
            time.sleep(0.2)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Done. Imported {imported}, skipped {skipped}, failed {failed}."
        ))
        if failed:
            self.stdout.write(
                "Some queries failed. If many failed, Google Books may have rate-limited "
                "your IP — that's normal for anonymous use. The system also tries Open "
                "Library as a fallback; if both failed, check your internet connection."
            )
