"""Author lookup via Open Library Authors API.

Returns a dict with name, bio, and (when available) a photo URL. Open Library
exposes authors at /authors/<id>.json and /search/authors.json. We pick the
first match for a name search, then fetch their detail record.

Results are cached in Django's cache for 24 hours so we don't hammer the API.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.core.cache import cache

log = logging.getLogger(__name__)

SEARCH_ENDPOINT = "https://openlibrary.org/search/authors.json"
DETAIL_ENDPOINT = "https://openlibrary.org/authors"
PHOTO_ENDPOINT = "https://covers.openlibrary.org/a/id"
HTTP_TIMEOUT_SECONDS = 10
CACHE_TTL = 60 * 60 * 24  # 24 hours


def _fetch_json(url: str) -> dict | None:
    req = Request(url, headers={"User-Agent": "PageTurner/1.0 (educational)"})
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.warning("Author API failed for %s: %s", url, exc)
        return None


def lookup_author(name: str) -> dict | None:
    """Return {name, bio, photo_url, work_count, top_subjects, ol_key} for the
    closest match to `name`, or None if not found / API unreachable."""
    name = (name or "").strip()
    if not name:
        return None

    # The catalogue often returns multiple authors; split commas to use the
    # primary author when our Book model concatenated several.
    primary = name.split(",")[0].strip()

    import hashlib
    cache_key = "author:" + hashlib.md5(primary.lower().encode("utf-8")).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None  # cache.get returns "" for "we searched, nothing found"

    search = _fetch_json(f"{SEARCH_ENDPOINT}?{urlencode({'q': primary, 'limit': 1})}")
    if not search:
        cache.set(cache_key, "", 60 * 5)  # short negative cache; retry in 5min
        return None

    docs = search.get("docs") or []
    if not docs:
        cache.set(cache_key, "", CACHE_TTL)
        return None

    top = docs[0]
    ol_key = (top.get("key") or "").replace("/authors/", "")
    if not ol_key:
        cache.set(cache_key, "", CACHE_TTL)
        return None

    detail = _fetch_json(f"{DETAIL_ENDPOINT}/{ol_key}.json")
    bio = ""
    if detail:
        bio_field = detail.get("bio")
        if isinstance(bio_field, dict):
            bio = (bio_field.get("value") or "").strip()
        elif isinstance(bio_field, str):
            bio = bio_field.strip()

    photo_id = (top.get("photos") or [None])[0]
    photo_url = f"{PHOTO_ENDPOINT}/{photo_id}-M.jpg" if photo_id else ""

    result = {
        "name": top.get("name") or primary,
        "bio": bio[:3000],
        "photo_url": photo_url,
        "work_count": int(top.get("work_count") or 0),
        "top_subjects": (top.get("top_subjects") or [])[:6],
        "birth_date": top.get("birth_date") or "",
        "ol_key": ol_key,
    }
    cache.set(cache_key, result, CACHE_TTL)
    return result
