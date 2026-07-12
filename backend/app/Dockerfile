FROM python:3.11-slim

# Postgres build deps + LibreOffice (DOCX -> PDF for admin ingestion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
