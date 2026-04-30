# Use a slim Python image
FROM python:3.12-slim

# Install 'uv' (the package manager shown in your folder)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files first (for caching)
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev

# ── FIX: DOWNLOAD THE AI MODEL INTO THE UV ENVIRONMENT ──
RUN uv run python -m spacy download en_core_web_sm

# Copy the rest of your application code
COPY . .

# Set environment variables for Cloud Run
ENV PORT=8080
EXPOSE 8080

# 1. Enable PostGIS -> 2. Run Migrations -> 3. Start Server
CMD ["sh", "-c", "uv run python init_db.py && uv run alembic upgrade head && uv run uvicorn main:app --host 0.0.0.0 --port 8080"]