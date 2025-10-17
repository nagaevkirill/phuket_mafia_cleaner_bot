# syntax=docker/dockerfile:1
FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# runtime пакеты (HTTPS сертификаты, часовой пояс по желанию)
RUN apk add --no-cache ca-certificates tzdata \
 && addgroup -S app && adduser -S -G app app

WORKDIR /app

# зависимости отдельно — для кэша
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# код
COPY . /app
RUN chown -R app:app /app

USER app

# бот/скрипт
CMD ["python", "-u", "app.py"]