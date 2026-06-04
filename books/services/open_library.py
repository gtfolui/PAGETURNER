"""Client for the Open Library API (https://openlibrary.org/developers/api).

Open Library is run by the Internet Archive, requires no API key, and has
much more permissive rate limits than the anonymous Google Books endpoint.
PageTurner uses it as the automatic fallback when Google Books is unavailable
or rate-limited — see `books/services/__init__.py` for the facade.

Exposes the same two functions as the Google Books client so the two are
drop-in compatible.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from books.models import Book

log = logging.getLogger(__name__)

SEARCH_ENDPOINT = "https://openlibrary.org/search.json"
WORK_ENDPOINT = "https://openlibrary.org/works"
COVER_ENDPOINT = "https://covers.openlibrary.org/b/id"
HTTP_TIMEOUT_SECONDS = 8

# Map Open Library subject strings to our internal genre slugs.
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


def _categorise(subjects: Iterable[str]) -> str:
    haystack = " ".join(subjects).lower() if subjects else ""
    for needle, slug in _GENRE_KEYWORDS.items():
        if needle in haystack:
            return slug
    return "literary"


def _deterministic_palette(key: str) -> tuple[str, str]:
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    bg = "#" + h[:6]
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    accent = "#{:02X}{:02X}{:02X}".format(
        min(255, r + 90), min(255, g + 90), min(255, b + 90)
    )
    return bg, accent


def _normalise_doc(doc: dict) -> dict | None:
    """Flatten an Open Library search hit into the fields we care about.
    Returns None if the doc is too incomplete to be useful."""
    work_key = (doc.get("key") or "").strip()  # e.g. '/works/OL82563W'
    if not work_key:
        return None
    # Strip the /works/ prefix — we store the bare id.
    external_id = work_key.replace("/works/", "")
    title = (doc.get("title") or "Untitled").strip()
    authors = doc.get("author_name") or ["Unknown author"]
    cover_id = doc.get("cover_i")
    cover_url = f"{COVER_ENDPOINT}/{cover_id}-M.jpg" if cover_id else ""
    isbn_list = doc.get("isbn") or []
    isbn = ""
    # Prefer a 13-digit ISBN when present
    for candidate in isbn_list:
        if len(candidate) == 13:
            isbn = candidate
            break
    if not isbn and isbn_list:
        isbn = isbn_list[0]

    bg, accent = _deterministic_palette(external_id)
    return {
        "external_id": external_id,
        "source": "openlibrary",
        "title": title[:200],
        "author": ", ".join(authors)[:120],
        "genre": _categorise(doc.get("subject") or []),
        "pages": int(doc.get("number_of_pages_median") or 0),
        "year": int(doc.get("first_publish_year") or 2024),
        "description": "",  # search results don't include description
        "isbn": isbn[:20] if isbn else "",
        "cover_url": cover_url,
        "cover_bg": bg,
        "cover_color": accent,
    }


def search(query: str, max_results: int = 20) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    params = {"q": query, "limit": max(1, min(40, int(max_results))), "fields":
              "key,title,author_name,cover_i,first_publish_year,isbn,subject,number_of_pages_median"}
    url = f"{SEARCH_ENDPOINT}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "PageTurner/1.0 (educational)"})
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("Open Library search failed for %r: %s", query, exc)
        return []

    docs = payload.get("docs") or []
    out = []
    for d in docs:
        normalised = _normalise_doc(d)
        if normalised:
            out.append(normalised)
    return out


def get_or_create_from_volume(external_id: str) -> Book | None:
    """Fetch one work by its Open Library id (e.g. 'OL82563W') and persist."""
    external_id = (external_id or "").strip().replace("/works/", "")
    if not external_id:
        return None

    existing = Book.objects.filter(source="openlibrary", external_id=external_id).first()
    if existing:
        return existing

    # Fetch the work record for a description; the search hit only had basics.
    url = f"{WORK_ENDPOINT}/{external_id}.json"
    req = Request(url, headers={"User-Agent": "PageTurner/1.0 (educational)"})
    description = ""
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            work = json.loads(resp.read().decode("utf-8", errors="replace"))
        desc_field = work.get("description")
        if isinstance(desc_field, dict):
            description = (desc_field.get("value") or "")[:2000]
        elif isinstance(desc_field, str):
            description = desc_field[:2000]
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("Open Library work fetch failed for %s: %s", external_id, exc)
        # Fall through — we'll create the book without a description.

    # Run a quick search by id to backfill author / cover / etc.
    searches = search(f"key:/works/{external_id}", max_results=1)
    if not searches:
        # Try a looser search with just the work id as text.
        searches = search(external_id, max_results=1)
    if not searches:
        return None

    data = searches[0]
    data["external_id"] = external_id
    if description:
        data["description"] = description

    if data.get("isbn"):
        by_isbn = Book.objects.filter(isbn=data["isbn"]).first()
        if by_isbn:
            return by_isbn

    book = Book.objects.create(**data)
    return book
