FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# /data — постоянный том: там живут santa.sqlite3 и secret_key
CMD gunicorn --preload --workers 2 --threads 4 --bind 0.0.0.0:${PORT:-8000} --access-logfile - wsgi:app
