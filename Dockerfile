# -----------------------------------------------------------------------------
# Stage 1: Build Frontend (Vite + React SPA)
# -----------------------------------------------------------------------------
FROM node:22-slim AS frontend-builder
WORKDIR /app

COPY package*.json ./
RUN npm ci --no-audit --no-fund

COPY . .
ENV VITE_API_MODE=live
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Runtime (Python FastAPI Backend + Worker Loop)
# -----------------------------------------------------------------------------
FROM python:3.12-slim

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

# Install Python backend dependencies
COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY . .

# Copy compiled frontend from Stage 1
COPY --from=frontend-builder /app/dist /app/dist

# Ensure required runtime directories exist and have proper ownership
RUN mkdir -p /app/resources/demo-fixtures/inbox /app/resources/demo-fixtures/attachments \
  && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

