#!/usr/bin/env bash
# Build script for Render (and similar platforms).
# Exit on first error.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Seed demo data on first deploy. Comment this out after launch
# if you don't want sample books and users in production.
python manage.py seed_data
