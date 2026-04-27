FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN addgroup --system svc && adduser --system --ingroup svc svc && chown -R svc:svc /app
USER svc
ENV PYTHONUNBUFFERED=1 SERVICE_NAME=position-manager SERVICE_PORT=8016
EXPOSE 8016
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -sf http://localhost:8016/health || exit 1
CMD ["python", "app.py"]
