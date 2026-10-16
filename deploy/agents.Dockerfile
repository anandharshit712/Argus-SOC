# Python image for the ingestor, the agents and one-shot jobs (seed, reset).
# Owner: Workstream B. Built from the repo root: docker compose builds it.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 argus

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY scripts ./scripts
COPY data ./data

USER argus
CMD ["argus-agents"]
