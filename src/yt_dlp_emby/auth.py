"""Login / cookies errors for YouTube and Dropout."""

from __future__ import annotations

YOUTUBE_COOKIES_HELP = (
    "YouTube blocked the download (sign in to confirm you are not a bot). "
    "Put a Netscape cookies.txt next to the command, or pass --cookies / --cookies-from-browser firefox."
)

DROPOUT_COOKIES_HELP = (
    "Dropout blocked the request (login required). "
    "Use a Netscape cookies file with _session for watch.dropout.tv "
    "(not the YouTube cookies file), or pass --cookies / --cookies-from-browser."
)


class YoutubeAuthError(RuntimeError):
    """YouTube required cookies / login to continue."""


class DropoutAuthError(RuntimeError):
    """Dropout required cookies / login to continue."""


_AUTH_NEEDLES = (
    "http error 401",
    "http error 403",
    "http error 407",
    "sign in",
    "not a bot",
    "login required",
    "only available for registered",
    "cookies are required",
    "please log in",
    "please sign in",
    "authentication required",
    "access denied",
)
_AUTH_STRONG = (
    "sign in",
    "not a bot",
    "login required",
    "cookies are required",
    "please log in",
    "please sign in",
    "only available for registered",
    "authentication required",
)
_NETWORK_NOISE = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "temporary failure",
    "connection refused",
    "connection reset",
    "name or service not known",
    "nodename nor servname",
    "network is unreachable",
    "no route to host",
    "broken pipe",
    "eof occurred",
    "ssl:",
    "certificate verify",
)


def looks_like_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if not any(needle in text for needle in _AUTH_NEEDLES):
        return False
    if any(noise in text for noise in _NETWORK_NOISE):
        return any(token in text for token in _AUTH_STRONG)
    return True


def is_dropout_url(url: str) -> bool:
    lowered = url.lower()
    return "dropout.tv" in lowered or "vhx.tv" in lowered


def auth_error_from_exception(url: str, exc: BaseException) -> RuntimeError | None:
    if not looks_like_auth_error(exc):
        return None
    if is_dropout_url(url):
        return DropoutAuthError(DROPOUT_COOKIES_HELP)
    return YoutubeAuthError(YOUTUBE_COOKIES_HELP)
