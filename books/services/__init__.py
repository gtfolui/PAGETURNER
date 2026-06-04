"""Unified book-source facade.

PageTurner can pull books from multiple trusted APIs. This module hides which
one was used from the rest of the application — views and management commands
just call `book_search()` and `import_book()`. The facade tries Google Books
first (richer metadata when available) and falls back to Open Library when
Google is rate-limited (HTTP 429), unauthorized (403 without an API key), or
unreachable.

Open Library is also chosen as the default when no `GOOGLE_BOOKS_API_KEY` is
configured, because the public Google Books endpoint is aggressively shared-
rate-limited and rarely usable for more than a handful of requests.
"""
from __future__ import annotations

import logging

from django.conf import settings

from books.models import Book
from . import google_books, open_library

log = logging.getLogger(__name__)


def _prefer_google() -> bool:
    """We only prefer Google Books when an API key is configured.
    Without a key, the anonymous endpoint is rate-limited so harshly that
    it's effectively unusable for more than one or two requests."""
    return bool(getattr(settings, "GOOGLE_BOOKS_API_KEY", "") or "")


def book_search(query: str, max_results: int = 20) -> list[dict]:
    """Search for books across providers. Returns a list of normalised dicts."""
    query = (query or "").strip()
    if not query:
        return []

    if _prefer_google():
        results = google_books.search(query, max_results=max_results)
        if results:
            return results
        log.info("Google Books returned no results for %r, trying Open Library", query)

    results = open_library.search(query, max_results=max_results)
    if results:
        return results

    # Last attempt: if we hadn't tried Google yet (no API key path), try it now
    # in case it works anyway. Cheap, since the call short-circuits on failure.
    if not _prefer_google():
        return google_books.search(query, max_results=max_results)

    return []


def import_book(external_id: str, source: str = "") -> Book | None:
    """Import a book by its provider id. If `source` is supplied ('google' or
    'openlibrary') we call that provider directly; otherwise we try Google
    first, then Open Library."""
    external_id = (external_id or "").strip()
    if not external_id:
        return None

    # Already imported under any source?
    existing = Book.objects.filter(external_id=external_id).first()
    if existing:
        return existing

    if source == "google":
        return google_books.get_or_create_from_volume(external_id)
    if source == "openlibrary":
        return open_library.get_or_create_from_volume(external_id)

    # Auto: try Google first if preferred, otherwise Open Library first.
    if _prefer_google():
        book = google_books.get_or_create_from_volume(external_id)
        if book:
            return book
        return open_library.get_or_create_from_volume(external_id)

    book = open_library.get_or_create_from_volume(external_id)
    if book:
        return book
    return google_books.get_or_create_from_volume(external_id)
