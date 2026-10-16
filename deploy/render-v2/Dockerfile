FROM python:3.12-slim
WORKDIR /app
COPY deploy/render-v2/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY deploy/render-v2/app_v2.py ./app_v2.py
ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "gunicorn --workers 1 --bind 0.0.0.0:$PORT app_v2:app"]
