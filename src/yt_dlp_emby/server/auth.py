"""Single-admin password auth and session secrets."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

AUTH_FILENAME = ".yt-dlp-emby-auth.json"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
SALT_BYTES = 16
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128


@dataclass
class AuthState:
    setup_required: bool
    session_secret: str
    password_hash: str | None = None
    salt: str | None = None
    # Bumped on every password change; stored in the session so a rotation
    # invalidates all other sessions (logout-all) even if a cookie signed with
    # the old secret is somehow still accepted.
    password_version: int = 0


def _auth_path(data_dir: Path) -> Path:
    return data_dir / AUTH_FILENAME


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DKLEN,
    )
    return digest.hex()


def _load_raw(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_raw(path: Path, data: dict[str, Any]) -> None:
    from yt_dlp_emby.cache import atomic_write_private

    atomic_write_private(path, json.dumps(data, indent=2) + "\n", mode=0o600)


def load_auth(data_dir: Path, environ: Mapping[str, str] | None = None) -> AuthState:
    if environ is None:
        environ = os.environ
    path = _auth_path(data_dir)
    raw = _load_raw(path)
    if raw is None:
        bootstrap = environ.get("YT_DLP_EMBY_PASSWORD", "").strip()
        if bootstrap:
            salt = secrets.token_bytes(SALT_BYTES)
            data = {
                "password_hash": _hash_password(bootstrap, salt),
                "salt": salt.hex(),
                "session_secret": secrets.token_urlsafe(32),
                "password_version": 0,
            }
            _write_raw(path, data)
            raw = data
            os.environ.pop("YT_DLP_EMBY_PASSWORD", None)
            pop = getattr(environ, "pop", None)
            if callable(pop):
                pop("YT_DLP_EMBY_PASSWORD", None)
        else:
            return AuthState(
                setup_required=True,
                session_secret=secrets.token_urlsafe(32),
            )
    return AuthState(
        setup_required=False,
        session_secret=str(raw["session_secret"]),
        password_hash=str(raw["password_hash"]),
        salt=str(raw["salt"]),
        password_version=int(str(raw.get("password_version", 0) or 0)),
    )


def setup_password(data_dir: Path, password: str, auth: AuthState) -> AuthState:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"password must be at most {MAX_PASSWORD_LEN} characters")
    if not auth.setup_required and _auth_path(data_dir).is_file():
        raise RuntimeError("already set up")
    salt = secrets.token_bytes(SALT_BYTES)
    data: dict[str, Any] = {
        "password_hash": _hash_password(password, salt),
        "salt": salt.hex(),
        "session_secret": secrets.token_urlsafe(32),
        "password_version": 0,
    }
    _write_raw(_auth_path(data_dir), data)
    return AuthState(
        setup_required=False,
        session_secret=data["session_secret"],
        password_hash=data["password_hash"],
        salt=data["salt"],
        password_version=0,
    )


def verify_password(password: str, auth: AuthState) -> bool:
    if auth.setup_required or not auth.password_hash or not auth.salt:
        return False
    salt = bytes.fromhex(auth.salt)
    expected = _hash_password(password, salt)
    return hmac.compare_digest(expected, auth.password_hash)


def change_password(data_dir: Path, current: str, new_password: str, auth: AuthState) -> AuthState:
    if auth.setup_required or not verify_password(current, auth):
        raise ValueError("current password is incorrect")
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if len(new_password) > MAX_PASSWORD_LEN:
        raise ValueError(f"password must be at most {MAX_PASSWORD_LEN} characters")
    salt = secrets.token_bytes(SALT_BYTES)
    data: dict[str, Any] = {
        "password_hash": _hash_password(new_password, salt),
        "salt": salt.hex(),
        # Rotate the signing secret AND bump the version: the middleware reads
        # the secret per request, and the version check below invalidates any
        # session that predates this rotation (logout-all).
        "session_secret": secrets.token_urlsafe(32),
        "password_version": auth.password_version + 1,
    }
    _write_raw(_auth_path(data_dir), data)
    return AuthState(
        setup_required=False,
        session_secret=data["session_secret"],
        password_hash=data["password_hash"],
        salt=data["salt"],
        password_version=data["password_version"],
    )
