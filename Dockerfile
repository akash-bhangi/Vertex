# ==============================================================
# Stage 1: Build the Next.js Frontend
# ==============================================================
FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app/frontend

# Copy frontend dependency manifests
COPY frontend/package*.json ./
RUN npm ci || npm install

# Copy frontend source code and build production assets
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_SUPABASE_URL=https://heezkejugtehennmiugd.supabase.co
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhlZXprZWp1Z3RlaGVubm1pdWdkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgwNjgyMTYsImV4cCI6MjEwMzY0NDIxNn0.Ft0oe-ked_Eiba9LPOmWbc1LHvRgq9DnD27q9FPj6L8
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
RUN npm run build

# ==============================================================
# Stage 2: Combined Production Runner (Python 3.12 + Node.js 20)
# ==============================================================
FROM python:3.12-slim-bookworm AS runner

# Install Node.js 20 and system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python backend dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend source code
COPY backend/ ./backend/

# Copy built frontend application and node_modules from builder
COPY --from=frontend-builder /app/frontend ./frontend

# Copy startup script and ensure Unix line endings + executable permissions
COPY start.sh ./
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Render provides the port in the $PORT environment variable (default 10000)
ENV PORT=10000
EXPOSE 10000

CMD ["./start.sh"]
