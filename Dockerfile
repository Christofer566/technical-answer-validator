FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TAV_HOST=0.0.0.0 \
    TAV_PORT=8080 \
    TAV_USAGE_DB=/data/usage.sqlite3

WORKDIR /app
COPY tav_api.py tav_core.py ./
RUN useradd --system --uid 10001 --no-create-home tav && mkdir /data && chown 10001:10001 /data
VOLUME ["/data"]
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["python", "-m", "tav_api"]
