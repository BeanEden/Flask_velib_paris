# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copie ton code
COPY . /app

# Installe les dépendances système (optionnel mais conseillé)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# Installe les requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copie le .env si nécessaire
COPY .env /app/.env

CMD ["python", "velib_to_mongo.py"]
