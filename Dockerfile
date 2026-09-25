FROM python:3.10-slim


RUN apt-get update && apt-get install -y ffmpeg nodejs curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -U yt-dlp


COPY . .

ENV PORT=8000
EXPOSE 8000


CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT
