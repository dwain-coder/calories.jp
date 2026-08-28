FROM python:3.12-slim

# Set env variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy lock and project files
COPY pyproject.toml uv.lock ./

# Install dependencies globally inside the container
RUN uv pip install --system -r pyproject.toml

# Copy the rest of the application
COPY . .

# Expose port
EXPOSE 8000

# Run FastAPI server
CMD ["python", "main.py", "serve"]
