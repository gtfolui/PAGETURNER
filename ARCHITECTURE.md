# PageTurner — System Architecture and Workflow

A Django-based social cataloging platform for readers, inspired by Goodreads. This document describes how the system is designed, how each subsystem works internally, and what design decisions make the platform realistic, scalable, and resistant to the kinds of abuse (fake accounts, fake reviews, duplicate book records, spam friend requests) that plague public social applications.

---

## 1. System Overview

PageTurner is a full-stack web application built on Django. Users register, verify their email, search for real books sourced from trusted external APIs, organize those books into personal shelves, rate and review them, follow other readers through a mutual friend system, participate in yearly reading challenges, and interact through an activity feed and notifications panel.

The application is structured as a classic three-tier system: a presentation layer rendered with Django templates and a small JavaScript module for asynchronous interactions; a business-logic layer composed of Django views, services, and signals; and a persistence layer built on a relational database (SQLite locally, PostgreSQL in production). External book data is fetched on demand from the Google Books API and stored in a normalized form, ensuring that the catalog reflects real, verifiable publications rather than user-generated entries.

The system is designed to be deployable to production hosting platforms such as Render, Railway, Heroku, or PythonAnywhere with no code changes — configuration is entirely environment-driven.

---

## 2. Component Responsibilities

**Presentation layer.** Django templates render pages server-side; the base template provides the topbar, sidebar, modal, toast, and message infrastructure. A single `app.js` module handles asynchronous interactions (saving books, sending friend requests, marking notifications read) via JSON requests, with CSRF protection handled transparently. The stylesheet uses CSS custom properties for theming so the interface can be rebranded without changing markup.

**Business-logic layer.** Two Django apps split the concerns: `accounts` owns authentication, user profiles, and email verification; `books` owns the catalog, shelves, ratings, reviews, friendships, notifications, activity, challenges, and moderation. A dedicated `books.services` package isolates external API integration from the request/response cycle so views never deal directly with HTTP clients or upstream payload shapes.

**Persistence layer.** Django's ORM mediates all database access. Models declare relationships and constraints declaratively, migrations track schema evolution, and querysets compose into efficient SQL. The default configuration uses SQLite for local development; production reads `DATABASE_URL` and switches to PostgreSQL automatically via `dj-database-url`.

**Authentication subsystem.** Uses Django's built-in authentication framework, which provides password hashing (PBKDF2 with SHA-256 by default), session management, CSRF protection, and login decorators out of the box. The framework is extended with an email-verification layer for accounts that need to perform social actions.

**Static and media.** WhiteNoise serves compressed static files in production directly from the web process, eliminating the need for a separate file server or CDN for the MVP. Book cover images are not stored locally — they are referenced by URL from Google Books, which keeps the database compact and offloads CDN concerns to the upstream provider.

---

## 3. Authentication and Email Verification

The authentication flow uses Django's `User` model paired with a one-to-one `UserProfile` extension. When a user submits the signup form, a `User` row is created with a hashed password, a `UserProfile` is auto-created via a `post_save` signal handler, and a verification token is generated using `secrets.token_urlsafe(32)`. A verification email is dispatched through Django's mail framework: in development, the console backend prints the link to stdout; in production, an SMTP backend (such as SendGrid, Mailgun, or AWS SES) sends a real message.

The verification link points to a URL containing the token. When clicked, the corresponding `UserProfile` is fetched, its `is_email_verified` flag is set, and the user is redirected to the home page with a success message. The token field has a database index for fast lookup.

Email verification is gated behind a feature flag (`REQUIRE_EMAIL_VERIFICATION`). When enabled, unverified users can still browse the catalog and organize books on their shelves, but cannot send friend requests or post reviews. This graduated permission model gives new users a useful first session while protecting the social surface area from spam accounts. Existing demo users created by the seed command are marked verified automatically so development workflows are not disrupted.

Passwords are never stored or transmitted in plaintext. Django's authentication framework hashes them using PBKDF2 with SHA-256 and a per-user salt; login validation compares hashes rather than plaintext. Sessions are stored server-side with cryptographically signed cookies on the client. In production mode, session and CSRF cookies are flagged `Secure`, the application forces HTTPS, and HSTS headers are configurable.

---

## 4. Real Book Catalog and API Integration

The catalog system is the central anti-fake-data mechanism. Users cannot manually create books. The `Book` model has these provenance fields:

- `source` — one of `google`, `openlibrary`, or `seed`
- `external_id` — the provider's stable identifier (Google Books volume ID)
- `isbn` — ISBN-13 preferred, ISBN-10 fallback

A unique constraint on `(source, external_id)` ensures the same Google Books volume cannot be imported twice. A secondary ISBN check during import catches cases where the same physical book appears under different provider IDs.

The integration is encapsulated in `books/services/google_books.py`, which exposes two functions:

- **`search(query, max_results)`** — Makes a GET request to `https://www.googleapis.com/books/v1/volumes` with the user's query, normalizes the JSON response into our internal shape, and returns a list of dictionaries. These results are not persisted; they exist only for the duration of the request.
- **`get_or_create_from_volume(volume_id)`** — Fetches one volume by ID, checks whether it already exists in the local catalog (by external_id or by ISBN), and either returns the existing `Book` or creates a new one.

This lazy-import pattern keeps the catalog focused on books that users actually interact with rather than mirroring Google's entire index. The service module handles network errors gracefully: timeouts, HTTP errors, and malformed JSON all log warnings and return empty results, so a temporary upstream outage degrades search but does not crash the discover page.

The user flow:

1. The user types a query on the Discover page.
2. Django's view queries the local catalog and calls `google_books.search()` in parallel.
3. Local results render as standard book cards; remote results render as cards with a "Google Books" badge.
4. Clicking a remote card calls the `import_book` endpoint, which invokes `get_or_create_from_volume()`, persists the book, and returns its local ID.
5. The UI then opens the book detail modal as if the book had always been local.

Genre classification is performed deterministically by matching keywords in the volume's category strings to a fixed map of internal genre slugs. Cover artwork uses the URL from Google Books when present, and falls back to a deterministic two-color gradient derived from a hash of the volume ID, so even books without artwork have a stable visual identity.

---

## 5. Shelves and the User-Book Relationship

Every interaction between a user and a book is mediated through the `UserBook` model, a many-to-many through-table with additional attributes. Its fields capture the shelf assignment (`reading`, `read`, `want`, `favorites`), reading progress (percent and current page), the user's rating (0–5, where 0 means unrated), the review text, and timestamps. A `unique_together` constraint on `(user, book)` enforces a one-to-one relationship per user-book pair, which is critical: it makes "one review per user per book" a database invariant rather than an application convention.

When the user submits a rating, review, or shelf change through the book detail modal, the view validates the payload, applies any moderation transformations (profanity masking, length truncation), and writes the result to the `UserBook` row. If a rating changed, the parent `Book.refresh_avg_rating()` method recomputes the cached average from the current set of rated `UserBook` rows. This denormalized field trades a small consistency cost (a brief delay if two users rate simultaneously) for a significant query speedup on the discover page, which can sort by `avg_rating` without aggregating across millions of rows.

Removing a book from a shelf deletes the `UserBook` row entirely. This is the correct semantic: the user has no relationship with the book anymore, and the row should not consume storage. The underlying `Book` record is preserved because other users may still have it on their shelves and the historical activity feed references it.

---

## 6. Ratings, Reviews, and Moderation

A review is a `UserBook` row with a non-empty `review` field. The view that handles review submission applies three checks before persisting:

1. **Authentication.** The view is decorated with `@login_required`, so anonymous users are redirected to the login page.
2. **Email verification.** If `REQUIRE_EMAIL_VERIFICATION` is on and the user's `is_email_verified` flag is false, the request is rejected with HTTP 403 and a clear error message. The user's shelf operation still succeeds; only the review portion is blocked.
3. **Profanity filter.** Review text is run through a token-replacement filter using a configurable blocklist (`PROFANITY_BLOCKLIST` env var). Matched substrings are replaced with asterisks. The filter is intentionally simple — it documents intent and provides a first line of defense, but real content moderation in a production deployment would integrate a managed service such as Google Perspective API or AWS Comprehend.

The `Book.avg_rating` field is recomputed whenever a new rating is saved. Reviews are visible to other users on the book's detail page and surface in the activity feed when posted.

The `Report` model implements user-driven moderation. Any user can file a report against a review, another user, or a book, choosing from a fixed set of reasons (spam, harassment, inappropriate content, fake/misleading, other). Reports land in a queue accessible only to staff users via Django Admin, where they can be marked resolved or dismissed with a single click using the registered bulk admin actions. The model tracks `resolved_at`, `resolved_by`, and the original `reporter` so the audit trail is complete.

---

## 7. Friend System

The friend system implements mutual approval to prevent unwanted connections and reduce spam. Three models work together:

- **`FriendRequest`** — Records every request between two users with a status (`pending`, `accepted`, `declined`), a created timestamp, and a responded timestamp. A partial unique constraint ensures at most one pending request exists between any sender-receiver pair at a time, so a user cannot spam the same target with duplicate requests.
- **`Friendship`** — Records a confirmed friendship as a directed row. When a request is accepted, two `Friendship` rows are created (A→B and B→A), both pointing back to the originating `FriendRequest` for auditability. This dual-row pattern makes "who are my friends" queries trivially fast in either direction without needing an OR clause.
- **`UserProfile.is_email_verified`** — Acts as a precondition: unverified users cannot send requests.

The flow:

1. User A clicks "Add friend" on User B's profile or in the discovery list.
2. The `send_friend_request` view validates: not self, A is verified, A is not already friends with B, A doesn't already have a pending request to B, and A has not exceeded their hourly rate limit.
3. If B has previously sent a request to A that is still pending, the system treats this as an implicit acceptance: it accepts B's existing request rather than creating a competing one. This handles the "race" gracefully.
4. Otherwise, a new `FriendRequest` is created with status `pending`, and a `Notification` is created for User B.
5. When User B views their friends page, the pending request appears at the top with accept/decline buttons.
6. Accepting creates the symmetric `Friendship` rows and notifies User A. Declining marks the request as `declined` (kept for audit, not deleted).

Rate limiting is configurable through `FRIEND_REQUEST_RATE_LIMIT_PER_HOUR` (default 20). The check counts how many requests the current user has sent in the past hour and returns HTTP 429 if the threshold is exceeded. This makes scripted spam ineffective: an attacker who automates the endpoint hits the wall after twenty requests per account per hour.

Unfriending deletes both `Friendship` rows but preserves the historical `FriendRequest`, so moderators can still see that the connection existed.

---

## 8. Activity Feed

The `Activity` model captures noteworthy user actions: starting a book, finishing one, rating one, adding one to favorites, or adding one to want-to-read. Whenever the `save_book` view processes a meaningful state change, it creates a corresponding `Activity` row referencing the user, the book, the action type, and (for ratings) the star count and review text.

The feed page queries the union of activity from the current user and their friends, ordered by recency, and renders each row through a partial template. Each card shows the actor's avatar, the action verb, the book, and any review excerpt. This denormalized event log is fast to query (one indexed timestamp scan) and easy to extend with new action types: adding "joined a challenge" or "completed a challenge" requires only a new enum value and an emit point in the relevant view.

For very high-traffic systems, the feed query can be precomputed into per-user inboxes (fan-out on write) using Celery and Redis, but for the realistic scale of a project app, the on-demand query is more than adequate.

---

## 9. Notifications

The `Notification` model is intentionally simple: a recipient user, an icon class, a text body, an `is_read` flag, and a timestamp. Notifications are created server-side when a noteworthy event occurs (friend request received, friend request accepted, the catalog can later add "your friend reviewed a book you have", "your challenge progress updated", etc.).

The base template queries unread notifications on every page load and renders the bell icon with a count badge. Clicking the bell navigates to the notifications page, which lists all notifications most-recent first. Clicking an individual notification posts to `mark_notif_read`, which updates the row and removes the unread styling.

For real-time delivery (browser push without polling), Django Channels and WebSockets can be layered on later. The current architecture isolates that concern behind the model so adding it is purely additive.

---

## 10. Reading Challenges

Each user can have one `ReadingChallenge` per year, storing a goal (number of books). A `unique_together` constraint on `(user, year)` prevents duplicates. The challenge page displays a progress ring computed by dividing the count of `UserBook` rows with `shelf="read"` and `updated_at__year=current_year` by the goal value. The goal is editable via a debounced range slider that posts to the `set_goal` endpoint, which validates the value and persists it.

Progress is computed at read time rather than incremented at write time, which keeps the model simple and the count always accurate. For very large user bases this could be cached, but the query is a simple indexed count against a small per-user slice of `UserBook` and runs in milliseconds.

---

## 11. Recommendations

The current recommendation engine is a simple content-based filter: it looks at the genres the user has rated highly, then surfaces other books in the same genres with high `avg_rating` that the user hasn't shelved yet. This is straightforward to compute (a few indexed queries) and gives reasonable results from day one without requiring a separate ML pipeline.

The architecture is set up so this can evolve into collaborative filtering as data accumulates: compute a sparse user-book matrix from `UserBook.rating`, find users with similar rating vectors using cosine similarity, and surface highly-rated books from those neighbors that the current user hasn't seen. This can be computed offline by a scheduled task and stored in a `Recommendation` table for fast lookup. For very large scale, a managed service such as AWS Personalize or a vector database such as Pinecone or pgvector becomes appropriate.

---

## 12. Statistics

The stats page aggregates each user's reading history into four headline numbers (books read, pages read, average rating given, reviews written) plus a top-genres breakdown and a five-year bar chart. All numbers are computed from `UserBook` and `Activity` queries at request time; no separate denormalized stats table is maintained. Django's ORM handles the aggregation efficiently using SQL `GROUP BY` and `Count` annotations.

Visualization is done with simple HTML and CSS bars driven by the percentages computed in Python; no JavaScript charting library is required for the current design, which keeps the page lightweight.

---

## 13. Database Design Summary

The relational structure is intentionally normalized. Key relationships:

- `User` 1-1 `UserProfile`
- `User` 1-N `UserBook` N-1 `Book`
- `User` 1-N `Friendship` N-1 `User` (self-referential, paired)
- `User` 1-N `FriendRequest` (sender, receiver) N-1 `User`
- `User` 1-N `Activity` N-1 `Book`
- `User` 1-N `Notification`
- `User` 1-N `ReadingChallenge`
- `User` 1-N `Report`

Important constraints:

- `Book(source, external_id)` is unique when `external_id` is non-empty (anti-duplicate)
- `UserBook(user, book)` is unique (one record per user-book; enforces one review per user per book)
- `FriendRequest(sender, receiver)` is unique when status is `pending` (anti-spam)
- `Friendship(user, friend)` is unique (anti-duplicate friendship rows)
- `ReadingChallenge(user, year)` is unique (one goal per user per year)

Indexes are defined on `Book.isbn`, `Book.external_id`, `UserProfile.email_verification_token`, and Django's default indexes on foreign keys cover the rest. The schema is designed to scale to tens of thousands of users without index tuning.

---

## 14. Security

The application implements a layered security model:

- **Password hashing** — PBKDF2 with SHA-256, per-user salt, configurable iteration count. Provided by Django.
- **Session management** — Server-side sessions, signed cookies, HTTPOnly flag, Secure flag in production.
- **CSRF protection** — Every state-changing request requires a CSRF token, enforced by Django middleware. The JavaScript module attaches it to JSON requests automatically.
- **HTTPS enforcement** — In production, `SECURE_SSL_REDIRECT`, HSTS headers, and `SECURE_PROXY_SSL_HEADER` ensure all traffic is encrypted.
- **Content security** — Output is auto-escaped by Django templates, preventing XSS. The `ALLOWED_HOSTS` setting prevents host header injection.
- **Email verification** — Optional gate on social actions, configurable per deployment.
- **Rate limiting** — Hourly cap on friend requests, with a clear path to extending to review submission and signup if abuse patterns emerge.
- **Input validation** — All POST endpoints validate types, ranges, and lengths before persisting. JSON payloads are parsed defensively with explicit `JSONDecodeError` handling.
- **Admin access** — Staff status required for Django Admin. Reports and moderation actions are restricted to staff.
- **Secret management** — All secrets (Django secret key, database URL, email credentials, API keys) are read from environment variables; nothing sensitive is committed to source control.
- **Dependency hygiene** — A pinned `requirements.txt` with version floors for security-relevant libraries (Django, gunicorn, whitenoise). Regular updates close known CVEs.

---

## 15. Copyright and Content Boundaries

PageTurner is explicitly **not** a reading application. The system stores metadata about books (titles, authors, descriptions, page counts, ratings) but does not host, display, or distribute the books themselves. Cover thumbnails are served by URL from Google Books, not re-hosted. Descriptions are stored verbatim from the Google Books API, which provides them under the API's terms of service for catalog use. Full book text is never imported or displayed; users cannot read copyrighted material inside the application.

Reviews are user-generated content, owned by their authors under the platform's terms of service. The moderation system gives the platform operator the ability to remove reviews that infringe copyright (e.g. quote extensively from the source book) or violate community standards.

This separation of cataloging from distribution is what makes PageTurner legally tractable as a public deployment: the platform fits within the same category as Goodreads, LibraryThing, and similar catalogs that operate under standard fair-use and metadata-licensing norms.

---

## 16. Deployment

The project is configured for one-command deployment to several modern hosting platforms.

**Render** is the recommended path because of its free tier and good ergonomics. The included `render.yaml` blueprint declares a web service running gunicorn, a managed Postgres database, and an auto-generated secret key. The `build.sh` script installs dependencies, collects static files, runs migrations, and seeds demo data. Pushing the repository to GitHub and pointing Render at it completes the deployment.

**Railway and Heroku** read the `Procfile`, which declares the web process and a release-phase migration. Environment variables (`SECRET_KEY`, `DEBUG=0`, `ALLOWED_HOSTS`, `DATABASE_URL`, email credentials, `GOOGLE_BOOKS_API_KEY`) are set through the dashboard.

**PythonAnywhere** is appealing in Asia-Pacific for latency reasons. The project layout is standard: a virtualenv, `pip install`, manual WSGI configuration pointing at `pageturner_project.wsgi`, and `python manage.py migrate` / `collectstatic` from a Bash console.

In all cases, the production checklist is:

1. Set `DEBUG=0`.
2. Set `SECRET_KEY` to a long, random value.
3. Set `ALLOWED_HOSTS` to the real domain.
4. Provision PostgreSQL and set `DATABASE_URL`.
5. Configure SMTP (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`).
6. Optionally set `GOOGLE_BOOKS_API_KEY` to lift the anonymous rate limit.
7. Set `REQUIRE_EMAIL_VERIFICATION=1` once SMTP is verified.
8. Run `python manage.py createsuperuser` to access the admin and moderation queue.

The application reads `.env` automatically when present (via `python-dotenv`), so local development needs only a `.env` file with sensible defaults.

---

## 17. Scaling Considerations

The current architecture is sized for tens of thousands of users with no changes. Beyond that, the natural evolution points are:

- **Database** — Add a read replica, route stats and feed queries to the replica.
- **Caching** — Add Redis, cache the rendered home and discover pages per user with short TTLs, cache `Book.avg_rating` invalidation events.
- **Background jobs** — Add Celery for sending verification emails, computing recommendations offline, and rebuilding the feed as fan-out on write.
- **Real-time** — Add Django Channels and Redis for WebSocket-based notifications.
- **Search** — Replace `icontains` queries with PostgreSQL full-text search (`SearchVector`), then graduate to Elasticsearch or Meilisearch if needed.
- **Static and media** — Move static files to a CDN-backed bucket; cover thumbnails can be cached server-side to reduce dependency on Google Books CDN.
- **API** — Add Django REST Framework on top of the existing models to expose a versioned JSON API. The existing view layer is structured so that the model and service code can be reused unchanged; only thin DRF viewsets and serializers need to be added. A React frontend can then consume that API while the Django templates remain available for SEO-friendly server-rendered pages.

---

## 18. End-User Workflow Summary

A new reader's journey through PageTurner looks like this:

1. They sign up with name, email, username, and password.
2. They click the verification link in their email; their `UserProfile.is_email_verified` flag flips to true.
3. They search the Discover page for a favourite book; results come back live from Google Books.
4. They click a result; the book is silently imported into the local catalog and the detail modal opens.
5. They mark it as Read, rate it five stars, and write a short review.
6. The system creates a `UserBook` row, recomputes the book's average rating, and emits an `Activity` event.
7. They search for other readers on the Friends page, send a friend request to one, and wait for acceptance.
8. When accepted, the symmetric `Friendship` rows are created and they appear in each other's social graphs.
9. Their home page now shows recent activity from their friend, recommended books in their preferred genres, and their progress against their yearly reading challenge.
10. Over time, statistics accumulate: pages read, top genres, year-over-year trends.

Every action in this flow is backed by a model row, every state change is validated, every social action is verified, and every book in the catalog can be traced back to a trusted external source. That is what separates a real social application from a class-project demo.
