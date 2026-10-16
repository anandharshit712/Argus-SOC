# Backend API image (Workstream C). Build from the repo root, because the backend runs on top
# of the main argus-soc package (graph tools library, learning service, settings):
#
#     docker build -f backend/Dockerfile -t argus-backend .
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 argus

# The main package first: it changes less often than the backend, so this layer is reused.
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY backend/pyproject.toml ./backend/
COPY backend/src ./backend/src
RUN pip install ./backend

USER argus
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)"
CMD ["argus-backend"]
