# Image de production pour l'interface web de shortmaker.
# Embarque ffmpeg (montage), espeak-ng (voix de secours hors-ligne) et les polices
# (sous-titres + bandeau CTA), puis sert web.py via gunicorn.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg espeak-ng fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# La plupart des hébergeurs injectent $PORT ; 8080 par défaut en local.
ENV PORT=8080
EXPOSE 8080

# 1 worker (les jobs sont stockés en mémoire), plusieurs threads pour le suivi de statut.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 -b 0.0.0.0:${PORT} --timeout 120 web:app"]
