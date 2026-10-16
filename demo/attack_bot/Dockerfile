# Argus attack-bot (Workstream A, demo harness). Internal only -- targets bundled demo containers.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" "httpx>=0.27,<1" "paramiko>=3.4,<4"
COPY campaigns.py ssh_campaign.py bot.py ./
EXPOSE 8000
CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8000"]
