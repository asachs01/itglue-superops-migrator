# Single stage build - simpler and faster
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Create non-root user and directories
RUN useradd -m -u 1000 migrator && \
    mkdir -p /app/exports /app/logs /app/data && \
    chown -R migrator:migrator /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=migrator:migrator . .

# Set environment variables
ENV PYTHONPATH=/app:$PYTHONPATH \
    PYTHONUNBUFFERED=1

# Switch to non-root user
USER migrator

# Create volume mount points
VOLUME ["/app/exports", "/app/logs", "/app/data"]

# Default command - show help
CMD ["python", "-m", "migrator.cli", "--help"]