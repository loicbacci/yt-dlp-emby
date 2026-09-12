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


@dataclass
class AuthState:
    setup_required: bool
    session_secret: str
    password_hash: str | None = None
    salt: str | None = None


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


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
            }
            _write_raw(path, data)
            raw = data
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
    )


def setup_password(data_dir: Path, password: str, auth: AuthState) -> AuthState:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if not auth.setup_required and _auth_path(data_dir).is_file():
        raise RuntimeError("already set up")
    salt = secrets.token_bytes(SALT_BYTES)
    data = {
        "password_hash": _hash_password(password, salt),
        "salt": salt.hex(),
        "session_secret": secrets.token_urlsafe(32),
    }
    _write_raw(_auth_path(data_dir), data)
    return AuthState(
        setup_required=False,
        session_secret=data["session_secret"],
        password_hash=data["password_hash"],
        salt=data["salt"],
    )


def verify_password(password: str, auth: AuthState) -> bool:
    if auth.setup_required or not auth.password_hash or not auth.salt:
        return False
    salt = bytes.fromhex(auth.salt)
    expected = _hash_password(password, salt)
    return hmac.compare_digest(expected, auth.password_hash)
