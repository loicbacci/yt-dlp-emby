from yt_dlp_emby.auth import looks_like_auth_error


def test_auth_error_matches_bot_check() -> None:
    assert looks_like_auth_error(RuntimeError("Sign in to confirm you’re not a bot"))
    assert looks_like_auth_error(RuntimeError("HTTP Error 403: Forbidden"))
    assert looks_like_auth_error(
        RuntimeError("ERROR: This video is only available for registered users")
    )


def test_auth_error_ignores_timeouts_and_generic_webpage_failures() -> None:
    assert not looks_like_auth_error(
        RuntimeError("ERROR: Unable to download webpage: The read operation timed out")
    )
    assert not looks_like_auth_error(
        RuntimeError(
            "ERROR: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in name resolution>"
        )
    )
    assert not looks_like_auth_error(RuntimeError("download did not produce an mkv"))
    assert not looks_like_auth_error(RuntimeError("TLS certificate verify failed"))
