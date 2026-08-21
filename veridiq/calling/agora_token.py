"""Agora AccessToken2 (007) RTC minting — stdlib only (HMAC-SHA256).

Minimal subset of Agora DynamicKey AccessToken2 / RtcTokenBuilder2.
Never logs App Certificate. LiveKit remains primary for meetings UI.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time
import zlib
from collections import OrderedDict
from hashlib import sha256
from typing import Union

ROLE_PUBLISHER = 1
ROLE_SUBSCRIBER = 2

_VERSION = "007"


def _pack_uint16(x: int) -> bytes:
    return struct.pack("<H", int(x))


def _pack_uint32(x: int) -> bytes:
    return struct.pack("<I", int(x))


def _pack_string(data: Union[str, bytes]) -> bytes:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _pack_uint16(len(data)) + data


def _pack_map_uint32(m: dict[int, int]) -> bytes:
    return _pack_uint16(len(m)) + b"".join(
        _pack_uint16(k) + _pack_uint32(v) for k, v in m.items()
    )


def _is_uuid32(data: str) -> bool:
    if len(data) != 32:
        return False
    try:
        bytes.fromhex(data)
    except ValueError:
        return False
    return True


class _ServiceRtc:
    k_service_type = 1
    k_privilege_join_channel = 1
    k_privilege_publish_audio = 2
    k_privilege_publish_video = 3
    k_privilege_publish_data = 4

    def __init__(self, channel_name: str = "", uid: Union[int, str] = 0):
        self._privileges: dict[int, int] = {}
        self._channel_name = channel_name.encode("utf-8")
        if uid in (0, "0", ""):
            self._uid = b""
        else:
            self._uid = str(uid).encode("utf-8")

    def add_privilege(self, privilege: int, expire: int) -> None:
        self._privileges[privilege] = int(expire)

    def service_type(self) -> int:
        return self.k_service_type

    def pack(self) -> bytes:
        privileges = OrderedDict(
            sorted(self._privileges.items(), key=lambda x: int(x[0]))
        )
        return (
            _pack_uint16(self.k_service_type)
            + _pack_map_uint32(privileges)
            + _pack_string(self._channel_name)
            + _pack_string(self._uid)
        )


def build_rtc_token(
    *,
    app_id: str,
    app_certificate: str,
    channel_name: str,
    uid: Union[int, str] = 0,
    role: int = ROLE_PUBLISHER,
    token_expire_sec: int = 3600,
    privilege_expire_sec: int | None = None,
) -> str:
    """Build an Agora AccessToken2 RTC token (version prefix ``007``)."""
    app_id = (app_id or "").strip()
    app_certificate = (app_certificate or "").strip()
    channel_name = (channel_name or "").strip()
    if not _is_uuid32(app_id) or not _is_uuid32(app_certificate):
        raise ValueError("invalid_agora_credentials")
    if not channel_name:
        raise ValueError("channel_required")

    token_expire = max(60, min(int(token_expire_sec or 3600), 86400))
    privilege_expire = (
        token_expire
        if privilege_expire_sec is None
        else max(60, min(int(privilege_expire_sec), 86400))
    )

    issue_ts = int(time.time())
    salt = secrets.SystemRandom().randint(1, 99999999)

    service = _ServiceRtc(channel_name, uid)
    service.add_privilege(_ServiceRtc.k_privilege_join_channel, privilege_expire)
    if int(role) == ROLE_PUBLISHER:
        service.add_privilege(_ServiceRtc.k_privilege_publish_audio, privilege_expire)
        service.add_privilege(_ServiceRtc.k_privilege_publish_video, privilege_expire)
        service.add_privilege(_ServiceRtc.k_privilege_publish_data, privilege_expire)

    app_id_b = app_id.encode("utf-8")
    app_cert_b = app_certificate.encode("utf-8")
    signing = hmac.new(_pack_uint32(issue_ts), app_cert_b, sha256).digest()
    signing = hmac.new(_pack_uint32(salt), signing, sha256).digest()

    signing_info = (
        _pack_string(app_id_b)
        + _pack_uint32(issue_ts)
        + _pack_uint32(token_expire)
        + _pack_uint32(salt)
        + _pack_uint16(1)
        + service.pack()
    )
    signature = hmac.new(signing, signing_info, sha256).digest()
    return _VERSION + base64.b64encode(
        zlib.compress(_pack_string(signature) + signing_info)
    ).decode("utf-8")
