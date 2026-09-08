"""Download pipeline. Filled in by later modules."""

from __future__ import annotations

from yt_emby.config import Settings


def run_download(url: str, settings: Settings, format_selector: str | None = None) -> int:
    if settings.dry_run:
        print(f"dry-run url={url}")
        print(f"library={settings.library}")
        print(f"old_dir={settings.old_dir}")
        print(f"ffmpeg={settings.ffmpeg}")
        if settings.season is not None:
            print(f"season={settings.season}")
        return 0
    raise NotImplementedError("download pipeline is not implemented yet")
