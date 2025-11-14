# Dockerfile
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers Python + requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Exposer le port Flask
EXPOSE 5000

# Lancer l'application
CMD ["python", "app.py"]
