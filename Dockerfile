# syntax=docker/dockerfile:1
# Re-pin these digests when Dependabot bumps the Docker ecosystem.
FROM node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9 AS web
WORKDIR /repo/web
RUN corepack enable && corepack prepare pnpm@10.6.5 --activate
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:0.8.15 AS uv

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
# ffmpeg pin note: the remediation plan asks for ffmpeg=7:* (ffmpeg 7.x), but
# Debian bookworm only ships ffmpeg 5.1.x (epoch 7:5.1.*). Exact patch (e.g.
# 7:5.1.6-0+deb12u1) drifts with point releases, so an exact `=` pin would rot;
# keep the distro package unpinned for reproducibility-via-digest (base image
# digest above is pinned). For ffmpeg 7, switch both stages to trixie-slim.
# tini/libatomic1/ca-certificates intentionally unpinned (small, stable, no ABI
# risk worth an exact pin).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        tini \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app -g 1000 \
    && useradd -r -g app -u 1000 -d /app app
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra server --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra server --no-dev
COPY --from=web /repo/web/dist /opt/web-dist
RUN mkdir -p /data \
    && chmod -R a+rX /opt/web-dist \
    && chown -R app:app /app /data /opt/web-dist
ENV PATH="/app/.venv/bin:/usr/local/bin:$PATH" \
    YT_DLP_EMBY_DATA=/data \
    YT_DLP_EMBY_WEB_DIST=/opt/web-dist \
    PORT=8080
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('PORT','8080'); urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health')"
ENTRYPOINT ["tini", "--"]
CMD ["yt-dlp-emby", "server", "--host", "0.0.0.0", "--data", "/data"]
