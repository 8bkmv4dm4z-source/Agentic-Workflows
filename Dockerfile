# Dockerfile -- single-stage build for FastAPI service
# python:3.12-slim base; psycopg[binary] bundles libpq (no system deps needed)
FROM python:3.12-slim

WORKDIR /app

# Copy dependency manifest first for layer caching
COPY pyproject.toml .

# Copy source (needed for pip install . to find the package)
COPY src/ src/

# Install production dependencies only (no [dev] extras)
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "agentic_workflows.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
