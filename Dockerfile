FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PLAYWRIGHT_HEADLESS=1
ENV PORT=10000
EXPOSE 10000
CMD ["sh","-c","gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:${PORT:-10000} app:app"]
