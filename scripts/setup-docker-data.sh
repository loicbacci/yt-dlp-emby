#!/usr/bin/env bash
# Copy yt-dlp-emby runtime data into a dedicated directory for Docker.
# Usage: sudo ./scripts/setup-docker-data.sh [SOURCE_DIR]
#        DEST=/docker/yt-dlp-emby OWNER_UID=$(id -u) ./scripts/setup-docker-data.sh --dry-run
set -euo pipefail

DEST="${DEST:-/docker/yt-dlp-emby}"
OWNER_UID="${OWNER_UID:-${UID:-1000}}"
OWNER_GID="${OWNER_GID:-${GID:-1000}}"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

if ! [[ "$OWNER_UID" =~ ^[0-9]+$ && "$OWNER_GID" =~ ^[0-9]+$ ]]; then
  echo "OWNER_UID/OWNER_GID must be numeric (got ${OWNER_UID}:${OWNER_GID})" >&2
  exit 1
fi

if [[ "${EUID:-$(id -u)}" -ne 0 && "$DRY_RUN" -eq 0 ]]; then
  echo "Re-run with sudo: sudo $0 ${1:-}" >&2
  exit 1
fi

copy_cmd() {
  local src="$1"
  local dest="$2"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$src" "$dest"
  else
    echo "rsync not found; using cp -a" >&2
    cp -a "$src" "$dest"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:-$(cd "$SCRIPT_DIR/.." && pwd)}"

if [[ ! -d "$SOURCE" ]]; then
  echo "Source directory does not exist: $SOURCE" >&2
  exit 1
fi

echo "Source: $SOURCE"
echo "Dest:   $DEST (owner ${OWNER_UID}:${OWNER_GID})"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "(dry-run: no files will be written)"
fi

if [[ "$DRY_RUN" -eq 0 && -d "$DEST" && -n "$(ls -A "$DEST" 2>/dev/null || true)" ]]; then
  backup="${DEST}.bak.$(date +%s)"
  echo "Backing up existing dest to $backup"
  cp -a "$DEST" "$backup"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  exit 0
fi

install -d -o "$OWNER_UID" -g "$OWNER_GID" -m 0755 "$DEST"
install -d -o "$OWNER_UID" -g "$OWNER_GID" -m 0755 "$DEST/cache"
install -d -o "$OWNER_UID" -g "$OWNER_GID" -m 0755 "$DEST/shows"

copy_if_exists() {
  local name="$1"
  local src="$SOURCE/$name"
  if [[ -e "$src" ]]; then
    if [[ "$name" == ".yt-dlp-emby-auth.json" ]]; then
      read -r -p "Copy auth file $name to $DEST? [y/N] " answer
      if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        echo "  skipped $name"
        return
      fi
    fi
    copy_cmd "$src" "$DEST/"
    echo "  copied $name"
  fi
}

echo "Copying files..."
# NOTE: plan.json / events.jsonl / download-only.json are intentionally NOT
# copied: stale queue files from the host must not seed a fresh container.
for f in \
  config.toml \
  dropout.yaml \
  youtube.yaml \
  cookies.txt \
  dropout-cookies.txt \
  .yt-dlp-emby-auth.json
do
  copy_if_exists "$f"
done

if [[ -d "$SOURCE/cache" ]]; then
  copy_cmd "$SOURCE/cache/" "$DEST/cache/"
  echo "  copied cache/"
fi

if [[ -d "$SOURCE/shows" ]]; then
  copy_cmd "$SOURCE/shows/" "$DEST/shows/"
  echo "  copied shows/"
fi

chown -R "${OWNER_UID}:${OWNER_GID}" "$DEST"
find "$DEST" -type d -exec chmod 0755 {} +
find "$DEST" -type f -exec chmod 0644 {} +
chmod 0600 "$DEST"/cookies.txt "$DEST"/dropout-cookies.txt "$DEST"/.yt-dlp-emby-auth.json 2>/dev/null || true
chmod 0640 "$DEST"/config.toml 2>/dev/null || true

echo ""
echo "Done. Data directory:"
ls -la "$DEST"
echo ""
echo "Update compose.yaml volumes to:"
echo "  - ${DEST}:/data"
echo ""
echo "Then: docker compose up -d --force-recreate"
