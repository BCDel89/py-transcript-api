FROM python:3.11-slim

WORKDIR /app

# git required for git+ pip dependencies
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

EXPOSE 8000

CMD ["python", "main.py"]
