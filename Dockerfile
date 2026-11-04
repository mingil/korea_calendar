FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul \
    KOREA_CAL_HOST=0.0.0.0 \
    KOREA_CAL_PORT=8500 \
    KOREA_CAL_AUTO_SYNC_MINUTES=720

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY seed/ ./seed/
COPY main.py run.sh ./
RUN chmod +x /app/run.sh && \
    mkdir -p /app/data /app/output/shared /app/logs && \
    chmod -R 777 /app/data /app/output /app/logs

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${KOREA_CAL_PORT:-8500}/health || exit 1

CMD ["python", "main.py"]
