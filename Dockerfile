FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

# Copy source
COPY src/ src/

# Run
CMD ["python", "-m", "src.main"]
