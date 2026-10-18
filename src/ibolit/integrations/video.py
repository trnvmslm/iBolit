"""Video calls via ZEGOCLOUD. The backend only issues a room token; the call itself runs in the ZEGO iOS SDK."""

from __future__ import annotations

import binascii
import datetime as dt
import json
import secrets
import struct
import time
from dataclasses import dataclass

from Crypto.Cipher import AES
from django.conf import settings

from ibolit.core import clock
from ibolit.integrations.base import note_mock

TOKEN_TTL_SECONDS = 3600


def generate_token04(app_id: int, server_secret: str, user_id: str, effective_seconds: int, payload: str = "") -> str:
    """ZEGO token04: AES-CBC-encrypted JSON, prefixed with expiry and IV, base64, version "04"."""
    secret = server_secret.encode()
    if len(secret) != 32:
        raise ValueError("ZEGO server secret must be 32 bytes")
    created = int(time.time())
    expire = created + effective_seconds
    info = {"app_id": app_id, "user_id": user_id, "nonce": secrets.randbits(31), "ctime": created, "expire": expire, "payload": payload}
    plain = json.dumps(info, separators=(",", ":")).encode()
    padding = 16 - len(plain) % 16
    iv = secrets.token_hex(8).encode()  # 16 ASCII characters, as in ZEGO's reference code
    encrypted = AES.new(secret, AES.MODE_CBC, iv).encrypt(plain + bytes([padding]) * padding)
    binary = struct.pack("!q", expire) + struct.pack("!h", len(iv)) + iv + struct.pack("!h", len(encrypted)) + encrypted
    return "04" + binascii.b2a_base64(binary, newline=False).decode()


@dataclass(frozen=True)
class VideoToken:
    provider: str
    app_id: int
    room_id: str
    user_id: str
    token: str
    expires_at: dt.datetime


def issue_token(*, room_id: str, user_id: str) -> VideoToken:
    expires_at = clock.now() + dt.timedelta(seconds=TOKEN_TTL_SECONDS)
    use_zego = settings.VIDEO_PROVIDER == "zego" and settings.ZEGO_APP_ID and len(settings.ZEGO_SERVER_SECRET) == 32
    if use_zego:
        token = generate_token04(settings.ZEGO_APP_ID, settings.ZEGO_SERVER_SECRET, user_id, TOKEN_TTL_SECONDS)
        return VideoToken("zego", settings.ZEGO_APP_ID, room_id, user_id, token, expires_at)
    note_mock("video")
    return VideoToken("mock", 0, room_id, user_id, f"mock-{secrets.token_hex(16)}", expires_at)
