FROM node:22-bookworm-slim AS web
WORKDIR /repo/web
RUN corepack enable && corepack prepare pnpm@10.6.5 --activate
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get purge -y curl \
    && apt-get autoremove -y
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY --from=web /repo/src/yt_dlp_emby/server/static /opt/web-dist
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --extra server --no-dev \
    && mkdir -p /data \
    && chmod 777 /data \
    && chmod -R a+rX /opt/web-dist
ENV PATH="/app/.venv/bin:$PATH" \
    YT_DLP_EMBY_DATA=/data \
    YT_DLP_EMBY_WEB_DIST=/opt/web-dist
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["yt-dlp-emby", "server", "--host", "0.0.0.0", "--data", "/data", "--proxy-headers"]
