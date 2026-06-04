"""Client for the Google Books API.

This module is the *only* source of new book records in production.
Books are never user-encoded. The flow is:

    1. User searches a title/author/ISBN in the Discover page.
    2. Django hits the Google Books volumes endpoint.
    3. Results are normalised into dicts (not yet saved).
    4. The user clicks a result — `get_or_create_from_volume` finds an
       existing Book or creates a new one keyed by (source, external_id).
    5. The book is shown in the modal and can be added to a shelf.

Open Library can be added later as a fallback; the public-facing shape of
`search()` and `get_or_create_from_volume()` is stable so views don't change.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.conf import settings

from books.models import Book

log = logging.getLogger(__name__)

GOOGLE_BOOKS_ENDPOINT = "https://www.googleapis.com/books/v1/volumes"
HTTP_TIMEOUT_SECONDS = 6

# Map Google Books category strings to our internal genre slugs.
_GENRE_KEYWORDS = {
    "fantasy": "fantasy",
    "science fiction": "scifi",
    "sci-fi": "scifi",
    "scifi": "scifi",
    "mystery": "mystery",
    "thriller": "mystery",
    "detective": "mystery",
    "literary": "literary",
    "fiction": "literary",
    "biography": "nonfiction",
    "history": "nonfiction",
    "self-help": "nonfiction",
    "business": "nonfiction",
    "non-fiction": "nonfiction",
    "nonfiction": "nonfiction",
    "romance": "romance",
    "love": "romance",
}


def _categorise(categories: Iterable[str]) -> str:
    """Pick the best internal genre slug from a list of Google categories."""
    haystack = " ".join(categories).lower() if categories else ""
    for needle, slug in _GENRE_KEYWORDS.items():
        if needle in haystack:
            return slug
    return "literary"


def _deterministic_palette(volume_id: str) -> tuple[str, str]:
    """Build a stable cover-background/accent colour pair from the volume id.
    Keeps cover art consistent for the same book across users."""
    h = hashlib.md5(volume_id.encode("utf-8")).hexdigest()
    bg = "#" + h[:6]
    # Blend toward white for the accent to keep contrast usable.
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    accent = "#{:02X}{:02X}{:02X}".format(
        min(255, r + 90), min(255, g + 90), min(255, b + 90)
    )
    return bg, accent


def _isbn_from_identifiers(identifiers: list[dict]) -> str:
    """Prefer ISBN-13, fall back to ISBN-10."""
    by_type = {i.get("type"): i.get("identifier", "") for i in identifiers or []}
    return by_type.get("ISBN_13") or by_type.get("ISBN_10") or ""


def _normalise_volume(volume: dict) -> dict:
    """Flatten a Google Books volume into the fields we care about."""
    info = volume.get("volumeInfo", {}) or {}
    volume_id = volume.get("id", "") or ""
    title = (info.get("title") or "Untitled").strip()
    if info.get("subtitle"):
        title = f"{title}: {info['subtitle']}"
    authors = info.get("authors") or ["Unknown author"]
    image_links = info.get("imageLinks") or {}
    cover_url = (
        image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or ""
    ).replace("http://", "https://")
    bg, accent = _deterministic_palette(volume_id or title)

    # publishedDate may be 'YYYY', 'YYYY-MM', or 'YYYY-MM-DD'.
    year = 0
    pd = info.get("publishedDate") or ""
    if pd[:4].isdigit():
        year = int(pd[:4])

    return {
        "external_id": volume_id,
        "source": "google",
        "title": title[:200],
        "author": ", ".join(authors)[:120],
        "genre": _categorise(info.get("categories") or []),
        "pages": int(info.get("pageCount") or 0),
        "year": year or 2024,
        "description": (info.get("description") or "")[:2000],
        "isbn": _isbn_from_identifiers(info.get("industryIdentifiers") or []),
        "cover_url": cover_url,
        "cover_bg": bg,
        "cover_color": accent,
    }


class GoogleBooksError(Exception):
    """Raised when the upstream API is unreachable or returns garbage."""


def search(query: str, max_results: int = 20) -> list[dict]:
    """Run a Google Books search and return a list of normalised dicts.
    These are *not* persisted — call `get_or_create_from_volume()` to do that.

    Empty query → empty list (don't waste an API call).
    Network failure → empty list and a logged warning (callers fall back to
    local search of already-imported books).
    """
    query = (query or "").strip()
    if not query:
        return []

    params = {
        "q": query,
        "maxResults": max(1, min(40, int(max_results))),
        "printType": "books",
    }
    api_key = getattr(settings, "GOOGLE_BOOKS_API_KEY", "") or ""
    if api_key:
        params["key"] = api_key

    url = f"{GOOGLE_BOOKS_ENDPOINT}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "PageTurner/1.0"})
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError) as exc:
        log.warning("Google Books search failed for %r: %s", query, exc)
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("Google Books returned non-JSON: %s", exc)
        return []

    items = payload.get("items") or []
    return [_normalise_volume(v) for v in items]


def get_or_create_from_volume(volume_id: str) -> Book | None:
    """Fetch one volume by its Google Books id and persist it (or return the
    existing Book record). This is what runs when the user clicks a search
    result and wants to interact with it."""
    volume_id = (volume_id or "").strip()
    if not volume_id:
        return None

    # Already imported?
    existing = Book.objects.filter(source="google", external_id=volume_id).first()
    if existing:
        return existing

    url = f"{GOOGLE_BOOKS_ENDPOINT}/{volume_id}"
    api_key = getattr(settings, "GOOGLE_BOOKS_API_KEY", "") or ""
    if api_key:
        url = f"{url}?key={api_key}"

    req = Request(url, headers={"User-Agent": "PageTurner/1.0"})
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("Google Books fetch failed for volume %s: %s", volume_id, exc)
        return None

    data = _normalise_volume(payload)
    if not data.get("external_id"):
        return None

    # Final dedupe by ISBN if we have one — different providers can hand back
    # the same physical book under different ids.
    if data["isbn"]:
        by_isbn = Book.objects.filter(isbn=data["isbn"]).first()
        if by_isbn:
            return by_isbn

    book = Book.objects.create(**data)
    return book
