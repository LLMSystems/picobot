# syntax=docker/dockerfile:1

# ---- Stage 1: build the Vue frontend ----
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ---- Stage 2: runtime (Python + browser stack) ----
FROM python:3.12-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    PICOBOT_FRONTEND_DIST=/app/frontend/dist

# System dependencies:
# - bubblewrap            : exec sandbox
# - nodejs/npm            : install the agent-browser CLI
# - xvfb                  : virtual display for headless Chrome
# - lib* / fonts          : Chrome runtime + CJK/emoji rendering for screenshots
# - git, ca-certificates  : common tool needs
RUN apt-get update && apt-get install -y --no-install-recommends \
      nodejs npm \
      bubblewrap \
      xvfb \
      git \
      ca-certificates \
      fontconfig fonts-noto-cjk fonts-noto-color-emoji fonts-dejavu-core fonts-liberation \
      libnspr4 libnss3 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
      libpango-1.0-0 libcairo2 libatspi2.0-0 libgtk-3-0 \
    && fc-cache -f \
    && npm install -g agent-browser \
    && agent-browser install \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e .

# Overlay the pre-built frontend (dist is .dockerignore'd from the context).
COPY --from=frontend /app/frontend/dist /app/frontend/dist

RUN chmod +x docker-entrypoint.sh && mkdir -p /app/data /app/workspaces

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
