#!/bin/sh
exec xvfb-run -a gunicorn --workers 1 --threads 8 --timeout 300 --access-logfile - --error-logfile - --bind 0.0.0.0:${PORT:-10000} app:app
