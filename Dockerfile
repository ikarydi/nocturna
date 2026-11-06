FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY nocturna ./nocturna
RUN pip install --no-cache-dir ".[postgres]"
COPY alembic.ini ./
COPY alembic ./alembic

ENV ACE_STEP_ENABLED=false
EXPOSE 8000
CMD ["sh", "-c", "uvicorn nocturna.api:app --host 0.0.0.0 --port 8000"]
