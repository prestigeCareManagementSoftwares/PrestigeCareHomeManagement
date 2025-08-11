#!/usr/bin/env bash
set -o errexit

# Upgrade pip first
pip install --upgrade pip

# Install requirements with explicit resolver
pip install --use-deprecated=legacy-resolver -r requirements.txt

# Standard deployment steps
python manage.py collectstatic --noinput
python manage.py migrate