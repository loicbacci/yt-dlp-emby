import xml.etree.ElementTree as ET
from pathlib import Path

from yt_dlp_emby.extract import EpisodeInfo
from yt_dlp_emby.nfo import write_episode_nfo, write_season_nfo, write_tvshow_nfo


def _text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    assert node is not None
    return node.text or ""


def test_tvshow_nfo_locks_youtube_id(tmp_path: Path) -> None:
    path = tmp_path / "tvshow.nfo"
    write_tvshow_nfo(
        path,
        title="Example Channel",
        plot="About the channel",
        channel_id="UCabc",
        named_seasons={1: "A Course"},
        premiered="2024-01-01",
    )
    root = ET.parse(path).getroot()
    assert root.tag == "tvshow"
    assert _text(root, "title") == "Example Channel"
    assert _text(root, "lockdata") == "true"
    assert _text(root, "studio") == "YouTube"
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.get("type") == "youtube"
    assert uid.text == "UCabc"
    named = root.find("namedseason")
    assert named is not None
    assert named.get("number") == "1"
    assert named.text == "A Course"
    xml = path.read_text(encoding="utf-8")
    assert "tmdbid" not in xml
    assert "tvdbid" not in xml
    assert '<?xml version="1.0"' in xml


def test_season_nfo(tmp_path: Path) -> None:
    path = tmp_path / "season.nfo"
    write_season_nfo(path, title="A Course", plot="Playlist plot", season=1)
    root = ET.parse(path).getroot()
    assert root.tag == "season"
    assert _text(root, "title") == "A Course"
    assert _text(root, "seasonnumber") == "1"
    assert _text(root, "lockdata") == "true"


def test_episode_nfo_from_info(tmp_path: Path) -> None:
    path = tmp_path / "ep.nfo"
    episode = EpisodeInfo(
        video_id="vid1",
        title="Intro",
        description="First lesson",
        playlist_index=1,
        upload_date="20240115",
        duration=125,
        webpage_url="https://www.youtube.com/watch?v=vid1",
    )
    write_episode_nfo(path, episode=episode, season=1, episode_number=1)
    root = ET.parse(path).getroot()
    assert root.tag == "episodedetails"
    assert _text(root, "title") == "Intro"
    assert _text(root, "season") == "1"
    assert _text(root, "episode") == "1"
    assert _text(root, "aired") == "2024-01-15"
    assert _text(root, "runtime") == "2"
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.get("type") == "youtube"
    assert uid.text == "vid1"
    assert _text(root, "lockdata") == "true"


def test_episode_plot_is_truncated(tmp_path: Path) -> None:
    path = tmp_path / "ep.nfo"
    episode = EpisodeInfo(
        video_id="vid1",
        title="Intro",
        description="x" * 20_000,
        playlist_index=1,
    )
    write_episode_nfo(path, episode=episode, season=1, episode_number=1)
    plot = _text(ET.parse(path).getroot(), "plot")
    assert len(plot) < 9000
