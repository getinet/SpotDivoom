FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

# tzdata: local time for the on-screen clock (set TZ in compose.yaml)
# fonts: bold fonts for the time & weather bar (Arial isn't available on Linux)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY spotdivoom ./spotdivoom
RUN mkdir -p /app/data

EXPOSE 5050
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/', timeout=4)"

CMD ["python", "main.py"]
