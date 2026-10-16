# Talos, the detection engine, at a pinned commit (docs/LLD.md §12). Owner: Workstream A.
#
# Talos is a dependency, never copied into this repo (rule 7): the image clones the public
# repository at TALOS_COMMIT. Compose builds it from the repo root:
#   build: {context: ., dockerfile: deploy/talos/Dockerfile}
#
# The container applies Talos's PostgreSQL migrations (idempotent: Talos keeps a ledger), then
# serves the report API on 0.0.0.0:8000 inside the Compose network. Needs TALOS_DB_DSN.
FROM python:3.12-slim

ARG TALOS_REPO=https://github.com/anandharshit712/Talos.git
# Oct 16, 2026: detection code unchanged since 15e732b, plus Docker packaging. Every test
# scenario matched Talos's expected output at this commit, locally and in Docker.
ARG TALOS_COMMIT=172866b31b95616ae4a7a5457972a80911c8dee0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The statistical path only: what the scenarios were verified with, and no API key needed.
    TALOS_LLM__ENABLED=false

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git init -q . && git remote add origin "$TALOS_REPO" \
    && git fetch -q --depth 1 origin "$TALOS_COMMIT" && git checkout -q FETCH_HEAD \
    && rm -rf .git && apt-get purge -y git && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
# Editable install: Talos reads config/ and db/ from its repository root (/app), which a plain
# `pip install .` would move to site-packages (see Talos's own deploy/docker/Dockerfile).
RUN pip install -e .

RUN useradd --system --uid 10001 --no-create-home talos
USER talos
EXPOSE 8000
CMD ["sh", "-c", "python scripts/apply_migrations.py --engine postgres && exec talos serve --host 0.0.0.0 --port 8000"]
