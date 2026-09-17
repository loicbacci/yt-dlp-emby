from yt_dlp_emby.series_ids import slugify, suggest_folder


def test_slugify_examples() -> None:
    assert slugify("Game Changer") == "game-changer"
    assert slugify("Dimension 20") == "dimension-20"
    assert slugify("  A/B  C!! ") == "a-b-c"
    assert slugify("---") == ""
    # Apostrophes become their own slug segment; file stems often drop them.
    assert slugify("Dimension 20's Adventuring Party") == "dimension-20-s-adventuring-party"


def test_suggest_folder() -> None:
    assert suggest_folder("Dimension 20", None) == "Dimension 20"
    assert suggest_folder("Dimension 20", 354216) == "Dimension 20 [tvdbid=354216]"
