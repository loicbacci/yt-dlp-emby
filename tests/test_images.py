from io import BytesIO
from pathlib import Path

from PIL import Image

from yt_emby.images import save_jpeg, write_image_from_bytes


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    image = Image.new("RGB", (8, 8), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_write_image_converts_png_to_jpeg(tmp_path: Path) -> None:
    dest = tmp_path / "poster.jpg"
    write_image_from_bytes(_png_bytes(), dest)
    assert dest.is_file()
    with Image.open(dest) as image:
        assert image.format == "JPEG"
        assert image.size == (8, 8)


def test_save_jpeg_from_existing_file(tmp_path: Path) -> None:
    src = tmp_path / "source.webp"
    Image.new("RGB", (4, 4), (0, 255, 0)).save(src, format="WEBP")
    dest = tmp_path / "fanart.jpg"
    save_jpeg(src, dest)
    with Image.open(dest) as image:
        assert image.format == "JPEG"
