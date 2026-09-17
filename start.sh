#!/bin/sh
exec gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:${PORT:-10000} app:app
