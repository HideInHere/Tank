FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN addgroup --system svc && adduser --system --ingroup svc svc && chown -R svc:svc /app
USER svc
ENV PYTHONUNBUFFERED=1 SERVICE_NAME=banks-service SERVICE_PORT=8009
EXPOSE 8009
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -sf http://localhost:8009/health || exit 1
CMD ["python", "app.py"]
