FROM python:3.11-slim

# Postgres build deps + LibreOffice (DOCX -> PDF) + ffmpeg (video -> Whisper)
RUN apt-get update && apt-get install --no-install-recommends -y \
    libpq-dev gcc \
    libreoffice-writer \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
