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

# The image ships the deployable extract, not the working corpus. Override
# DATABASE_PATH to point at a mounted volume if you upload the full database.
ENV DATABASE_PATH=data/metadata/site.db

# Hosted platforms inject $PORT; serve falls back to 8000 when it is unset.
EXPOSE 8000

CMD ["python", "main.py", "serve"]
