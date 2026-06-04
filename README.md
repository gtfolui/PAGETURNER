# PageTurner

A Goodreads-style book tracking app built with Django. Track what you're reading, set yearly goals, follow friends, and rate books.

## Features

- **Authentication** with optional email verification (signup, login, logout, token-based verify)
- **Real book catalog** sourced live from the Google Books API — no manually-encoded books, automatic dedupe by ISBN and provider id
- **Personal shelves**: Currently Reading, Read, Want to Read, Favorites
- **Reading progress** tracking with percentage and current page
- **Star ratings and reviews** with one-review-per-user-per-book enforced at the schema level, configurable profanity filter
- **Yearly reading challenges** with progress ring
- **Genre-filterable Discover page** that merges local catalog with live Google Books results
- **Activity feed** from confirmed friends
- **Mutual-approval friend system**: friend requests (pending / accepted / declined), per-hour rate limiting, counter-request shortcut, unfriend
- **Notifications** for friend requests, acceptances, and other events
- **Moderation**: user-submitted reports for reviews / users / books, reviewable in Django admin with bulk resolve/dismiss actions
- **Personal reading statistics** (top genres, pages, yearly trend)
- **Mobile-responsive UI**

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the complete technical writeup.

## Tech stack

- Django 4.2+
- SQLite for local dev, Postgres for production (via `DATABASE_URL`)
- WhiteNoise for static files
- Gunicorn as the WSGI server
- Tabler icons (CDN) and Google Fonts

## Local setup

```bash
# 1. Clone and enter the project
cd pageturner

# 2. Create a virtualenv
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set SECRET_KEY to a random string

# 5. Run migrations and seed demo data
python manage.py migrate
python manage.py seed_data

# 6. Start the dev server
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

### Demo accounts

The `seed_data` command creates seven demo users. The primary one is:

- **Username:** `jamie`
- **Password:** `readwell123`

Other seeded users (`maya`, `sarah`, `marcus`, `elena`, `david`, `priya`) share the same password.

You can also create a fresh account via the signup page.

## Building the book catalog

PageTurner sources all books from trusted external APIs — **Open Library** (the default, no API key needed) and **Google Books** (used when a `GOOGLE_BOOKS_API_KEY` is configured). The catalog grows in two ways:

1. **Live search** — type a title or author into the search bar and real results appear with a "Google Books" or "Open Library" badge. Click one to import it into your local catalog.
2. **Bulk import** — `python manage.py import_popular_books` fetches a curated list of ~20 well-known titles (Harry Potter, Dune, Atomic Habits, etc.) and imports them all at once.

```bash
python manage.py import_popular_books            # add real books to the catalog
python manage.py import_popular_books --replace  # delete demo books first, then import
```

If `seed_data` ran while you were offline, the catalog will contain manually-encoded fallback books labeled `source="seed"`. Run `import_popular_books --replace` once you're online to swap them for real Google Books records.

## Deployment

### Render (recommended — has a free tier)

1. Push this repo to GitHub.
2. Sign in to [render.com](https://render.com) and create a new **Blueprint**.
3. Point it at your repo. The included `render.yaml` provisions a web service plus a free Postgres database and runs `build.sh` automatically.
4. Wait for the build to finish, then open the assigned `.onrender.com` URL.

### Railway / Heroku

1. Set these environment variables in the dashboard:
   - `SECRET_KEY` — long random string
   - `DEBUG` — `0`
   - `ALLOWED_HOSTS` — your domain, e.g. `myapp.up.railway.app`
   - `DATABASE_URL` — Postgres connection string (Railway adds this automatically when you attach a Postgres plugin)
2. Push. The included `Procfile` handles boot and migrations.
3. To seed demo data, run `python manage.py seed_data` once from the platform's shell.

### PythonAnywhere

PythonAnywhere has good latency in Asia-Pacific.

1. Upload the project or `git clone` it on a Bash console.
2. Create a virtualenv, `pip install -r requirements.txt`.
3. Add a web app pointing to `pageturner_project/wsgi.py`.
4. Set environment variables in the WSGI file or via the dashboard.
5. Run `python manage.py migrate` and `python manage.py collectstatic --noinput`.
6. Reload the web app.

### Environment variables

| Variable                            | Purpose                                                    | Required        |
|-------------------------------------|------------------------------------------------------------|-----------------|
| `SECRET_KEY`                        | Django cryptographic key                                   | Yes             |
| `DEBUG`                             | `1` for dev, `0` for production                            | Yes             |
| `ALLOWED_HOSTS`                     | Comma-separated host list                                  | Yes in prod     |
| `DATABASE_URL`                      | Postgres connection string                                 | No (SQLite default) |
| `GOOGLE_BOOKS_API_KEY`              | Optional API key for higher rate limits                    | No              |
| `REQUIRE_EMAIL_VERIFICATION`        | `1` to gate friend requests / reviews on verified email    | No (off by default) |
| `FRIEND_REQUEST_RATE_LIMIT_PER_HOUR`| Max friend requests per user per hour (default 20)         | No              |
| `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP settings for prod email           | Prod only       |
| `DEFAULT_FROM_EMAIL`                | "From" address on verification emails                      | No              |
| `PROFANITY_BLOCKLIST`               | Comma-separated words to filter from reviews               | No              |

See [ARCHITECTURE.md](./ARCHITECTURE.md) for a full technical writeup: data model, request lifecycle, anti-spam design, moderation flow, and deployment notes.

## Project layout

```
pageturner/
├── pageturner_project/   # Django project settings, root urls, wsgi
├── accounts/             # User auth, signup form, profile model
├── books/                # Books, shelves, friends, notifications, stats
│   └── management/commands/seed_data.py
├── templates/            # base.html + per-page templates
├── static/               # css, js
├── requirements.txt
├── Procfile
├── render.yaml
├── build.sh
└── manage.py
```

## Useful commands

```bash
python manage.py seed_data           # populate demo data
python manage.py seed_data --reset   # wipe and re-seed
python manage.py createsuperuser     # admin user for /admin/
python manage.py collectstatic       # bundle static files
```

## License

MIT — do whatever you like with it.
