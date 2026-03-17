FROM python:3.12-slim

# Install system dependencies for Playwright + system Chromium (ARM compatible)
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright — skip browser download, we use system Chromium
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN playwright install-deps chromium 2>/dev/null || true

# Tell Playwright to use the system-installed Chromium
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

# Copy source
COPY src/ src/

# Run
CMD ["python", "-m", "src.main"]
