FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
COPY deploy/render-v2/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY deploy/render-v2/app_v2.py ./app_v2.py
COPY deploy/render-v2/collector_v2.py ./collector_v2.py
COPY deploy/render-v2/group_runner.py ./group_runner.py
ENV PLAYWRIGHT_HEADLESS=0
ENV TZ=Asia/Bangkok
ENV PORT=10000
EXPOSE 10000
CMD ["sh","-c","xvfb-run -a gunicorn --workers 1 --timeout 90 --bind 0.0.0.0:${PORT:-10000} app_v2:app"]
