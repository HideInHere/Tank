FROM python:3.12-slim

LABEL maintainer="HideInHere" \
      description="Tank Agent — persistent AI trading agent for openclaw gateway"

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates jq && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Agent source (copied from cloned repo)
COPY agent/ ./agent/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Non-root user
RUN useradd -m -u 1000 tankagent && chown -R tankagent:tankagent /app
USER tankagent

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TANK_AGENT_MODE=persistent

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:9000/health || exit 1

EXPOSE 9000

ENTRYPOINT ["/entrypoint.sh"]
