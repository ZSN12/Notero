# ============================================
# Notero - Production Dockerfile
# Multi-stage build: frontend (Vite) + backend (FastAPI)
# ============================================

# ------------------ Stage 1: Build frontend ------------------
FROM node:20-alpine AS frontend-builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ------------------ Stage 2: Python dependencies ------------------
FROM python:3.11-slim AS python-deps

WORKDIR /deps

# Install build dependencies for packages that compile C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

# ------------------ Stage 3: Production runtime ------------------
FROM python:3.11-slim AS backend

LABEL org.opencontainers.image.title="Notero"
LABEL org.opencontainers.image.description="AI learning workbench for Chinese classrooms"

WORKDIR /app

# Install runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r notero && useradd -r -g notero notero

# Copy installed Python packages from deps stage
COPY --from=python-deps /root/.local /home/notero/.local
ENV PATH=/home/notero/.local/bin:$PATH

# Copy application code
COPY backend/ ./
COPY --from=frontend-builder /app/dist ./static

# Ensure permissions for non-root user
RUN chown -R notero:notero /app /home/notero

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
# Prevent create_all fallback in production; migrations must run via Alembic
ENV ALLOW_CREATE_ALL_FALLBACK=0

USER notero

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fs http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
