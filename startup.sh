#!/bin/bash
# Azure App Service startup script

echo "=========================================="
echo "LensLoft Photo Share App - Startup Script"
echo "=========================================="

# Download required NLTK data for TextBlob
echo "Downloading NLTK data for sentiment analysis..."
python -m textblob.download_corpora 2>/dev/null || python -c "import nltk; nltk.download('brown'); nltk.download('punkt')" 2>/dev/null

# Create instance folder if not exists
mkdir -p /home/site/wwwroot/instance

# Set environment variables for Flask
export FLASK_APP=app.py
export PYTHONUNBUFFERED=1

echo "Starting Gunicorn server..."
exec gunicorn --bind 0.0.0.0:8000 --workers 4 --worker-class sync --timeout 60 --access-logfile - --error-logfile - app:app
