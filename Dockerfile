FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-libtorrent \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY .env.example .env

CMD ["python", "-m", "movie_recommender", "run", "--daemon"]
