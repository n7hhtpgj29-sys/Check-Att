FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
COPY deploy/render-v2/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY deploy/render-v2/app_v2.py ./app_v2.py
COPY deploy/render-v2/collector_v2.py ./collector_v2.py
COPY deploy/render-v2/group_runner.py ./group_runner.py
COPY deploy/render-v2/checkpoint_store.py ./checkpoint_store.py
COPY deploy/render-v2/webhook_bridge.py ./webhook_bridge.py
COPY deploy/render-v2/scheduler_v2.py ./scheduler_v2.py
COPY deploy/render-v2/gunicorn_config.py ./gunicorn_config.py
COPY deploy/render-v2/fast_collector.py ./fast_collector.py
ENV PLAYWRIGHT_HEADLESS=0
ENV TZ=Asia/Bangkok
ENV PORT=10000
EXPOSE 10000
CMD ["sh","-c","xvfb-run -a gunicorn --config gunicorn_config.py --workers 1 --worker-class gthread --threads 4 --timeout 360 --bind 0.0.0.0:${PORT:-10000} app_v2:app"]
