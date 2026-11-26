"""Antarmuka PlurkClient. Bot TIDAK PERNAH memanggil Plurk langsung; selalu lewat kelas ini.

Catatan semantik: get_responses() mengembalikan balasan dengan ID > setelah_id, urut ID naik.
(API asli memakai offset `from_response`; RealPlurk yang menerjemahkannya, tahap 4.)"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class PlurkError(Exception):
    """Error dari Plurk yang tidak dikenali secara khusus."""


class AntiFlood(PlurkError):
    """anti-flood-same-content / anti-flood-too-many-new: coba lagi tick berikutnya."""


class TokenDitolak(PlurkError):
    """401: token tidak valid. Bot berhenti memposting."""


@dataclass(frozen=True)
class PlurkUser:
    id: int
    nick: str


@dataclass(frozen=True)
class PlurkResponse:
    id: int
    plurk_id: int
    user_id: int
    nick: str
    content: str
    posted: datetime


@dataclass(frozen=True)
class Mention:
    """Alert 'mentioned'. response_id 0 = mention di plurk itu sendiri."""

    plurk_id: int
    response_id: int
    user_id: int
    nick: str
    posted: datetime


@dataclass(frozen=True)
class PlurkInfo:
    plurk_id: int
    owner_id: int
    content: str
    posted: datetime


class PlurkClient(Protocol):
    def whoami(self) -> PlurkUser: ...

    def add_plurk(
        self, content: str, qualifier: str = ":", limited_to: list[int] | None = None, no_comments: int = 0
    ) -> int: ...

    def add_response(self, plurk_id: int, content: str, qualifier: str = ":") -> int: ...

    def get_responses(self, plurk_id: int, setelah_id: int = 0) -> list[PlurkResponse]: ...

    def accept_friends(self) -> None: ...

    def get_mentions(self) -> list[Mention]: ...

    def get_plurk(self, plurk_id: int) -> PlurkInfo: ...

    def get_friend_ids(self) -> set[int]: ...


def tautan_plurk(plurk_id: int) -> str:
    """URL publik plurk: https://www.plurk.com/p/<id basis 36>."""
    angka, digit = plurk_id, "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while True:
        angka, sisa = divmod(angka, 36)
        s = digit[sisa] + s
        if angka == 0:
            return f"https://www.plurk.com/p/{s}"
