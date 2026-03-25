FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV and PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx libglib2.0-0 libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY seed_data.py .
COPY data/grading_brain.md data/grading_brain.md

# Create data directories
RUN mkdir -p data/db data/logs

# Expose port
EXPOSE 8741

# Run in cloud mode
ENV RKT_MODE=cloud
ENV RKT_ENV=production

CMD ["python", "-c", "from app.main import main; main()"]
