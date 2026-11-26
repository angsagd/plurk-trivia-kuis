"""FakePlurk: Plurk tiruan untuk dev & tes. Disimpan di SQLite (file dev bersama, atau :memory: untuk tes)
supaya CLI `simulasi` / `thread` bisa membaca dan menambah balasan ke thread yang dibuat proses bot."""

import sqlite3
from datetime import datetime

from app.clock import Clock, ke_wib
from app.plurk.client import AntiFlood, Mention, PlurkError, PlurkInfo, PlurkResponse, PlurkUser

BOT = PlurkUser(1, "kuisbot")
BATAS_TEKS = 360


class Crash(BaseException):  # noqa: N818
    """Simulasi proses mati mendadak (tes ketahanan); BaseException agar lolos dari `except Exception`."""


class FakePlurk:
    def __init__(self, clock: Clock, path: str = ":memory:"):
        self.clock = clock
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS plurks (id INTEGER PRIMARY KEY, owner_id INTEGER, content TEXT,
                qualifier TEXT, limited_to TEXT, posted TEXT);
            CREATE TABLE IF NOT EXISTS responses (id INTEGER PRIMARY KEY AUTOINCREMENT, plurk_id INTEGER,
                user_id INTEGER, nick TEXT, content TEXT, posted TEXT);
            CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, plurk_id INTEGER,
                response_id INTEGER, user_id INTEGER, nick TEXT, posted TEXT);
            CREATE TABLE IF NOT EXISTS friends (user_id INTEGER PRIMARY KEY);
            """
        )
        # Untuk tes: exception yang dilempar berurutan pada add_* berikutnya, dan Crash setelah n posting.
        self.gagal: list[BaseException] = []
        self.crash_setelah: int | None = None

    # ------------------------------------------------------------ PlurkClient

    def whoami(self) -> PlurkUser:
        return BOT

    def _sebelum_posting(self, content: str) -> None:
        if self.crash_setelah is not None:
            if self.crash_setelah <= 0:
                self.crash_setelah = None
                raise Crash("simulasi proses mati sebelum posting")
            self.crash_setelah -= 1
        if self.gagal:
            raise self.gagal.pop(0)
        if len(content) > BATAS_TEKS:
            raise PlurkError(f"content too long ({len(content)} > {BATAS_TEKS})")

    def _waktu(self) -> str:
        return self.clock.now().isoformat()

    def add_plurk(
        self, content: str, qualifier: str = ":", limited_to: list[int] | None = None, no_comments: int = 0
    ) -> int:
        self._sebelum_posting(content)
        baru = (self.db.execute("SELECT COALESCE(MAX(id), 1000000) FROM plurks").fetchone()[0]) + 1
        self.db.execute(
            "INSERT INTO plurks VALUES (?, ?, ?, ?, ?, ?)",
            (baru, BOT.id, content, qualifier, ",".join(map(str, limited_to or [])), self._waktu()),
        )
        return baru

    def add_response(self, plurk_id: int, content: str, qualifier: str = ":") -> int:
        self._sebelum_posting(content)
        terakhir = self.db.execute(
            "SELECT user_id, content FROM responses WHERE plurk_id = ? ORDER BY id DESC LIMIT 1", (plurk_id,)
        ).fetchone()
        if terakhir == (BOT.id, content):
            raise AntiFlood("anti-flood-same-content")
        return self._tambah(plurk_id, BOT.id, BOT.nick, content, self._waktu())

    def get_responses(self, plurk_id: int, setelah_id: int = 0) -> list[PlurkResponse]:
        rows = self.db.execute(
            "SELECT id, plurk_id, user_id, nick, content, posted FROM responses"
            " WHERE plurk_id = ? AND id > ? ORDER BY id",
            (plurk_id, setelah_id),
        ).fetchall()
        return [PlurkResponse(r[0], r[1], r[2], r[3], r[4], datetime.fromisoformat(r[5])) for r in rows]

    def accept_friends(self) -> None:
        return None

    def get_mentions(self) -> list[Mention]:
        """Seperti /APP/Alerts/getHistory: 30 alert 'mentioned' terakhir."""
        rows = self.db.execute(
            "SELECT plurk_id, response_id, user_id, nick, posted FROM alerts ORDER BY id DESC LIMIT 30"
        ).fetchall()
        return [Mention(r[0], r[1], r[2], r[3], datetime.fromisoformat(r[4])) for r in rows]

    def get_plurk(self, plurk_id: int) -> PlurkInfo:
        r = self.db.execute(
            "SELECT id, owner_id, content, posted FROM plurks WHERE id = ?", (plurk_id,)
        ).fetchone()
        if r is None:
            raise PlurkError(f"plurk {plurk_id} tidak ada")
        return PlurkInfo(r[0], r[1], r[2], datetime.fromisoformat(r[3]))

    def get_friend_ids(self) -> set[int]:
        return {r[0] for r in self.db.execute("SELECT user_id FROM friends")}

    # ------------------------------------------------------------ alat simulasi

    def _tambah(self, plurk_id: int, user_id: int, nick: str, content: str, posted: str) -> int:
        if self.db.execute("SELECT 1 FROM plurks WHERE id = ?", (plurk_id,)).fetchone() is None:
            raise PlurkError(f"plurk {plurk_id} tidak ada")
        cur = self.db.execute(
            "INSERT INTO responses (plurk_id, user_id, nick, content, posted) VALUES (?, ?, ?, ?, ?)",
            (plurk_id, user_id, nick, content, posted),
        )
        rid = int(cur.lastrowid or 0)
        self._cek_mention(plurk_id, rid, user_id, nick, content, posted)
        return rid

    def _cek_mention(
        self, plurk_id: int, response_id: int, user_id: int, nick: str, content: str, posted: str
    ):
        if user_id != BOT.id and f"@{BOT.nick}".lower() in content.lower():
            self.db.execute(
                "INSERT INTO alerts (plurk_id, response_id, user_id, nick, posted) VALUES (?, ?, ?, ?, ?)",
                (plurk_id, response_id, user_id, nick, posted),
            )

    def inject_plurk(self, user_id: int, nick: str, content: str, posted: datetime | None = None) -> int:
        """Plurk milik pemain tiruan (mis. berisi mention ke bot)."""
        waktu = ke_wib(posted).isoformat() if posted else self._waktu()
        baru = (self.db.execute("SELECT COALESCE(MAX(id), 1000000) FROM plurks").fetchone()[0]) + 1
        self.db.execute(
            "INSERT INTO plurks VALUES (?, ?, ?, ?, ?, ?)", (baru, user_id, content, ":", "", waktu)
        )
        self._cek_mention(baru, 0, user_id, nick, content, waktu)
        return baru

    def tambah_teman(self, *user_ids: int) -> None:
        self.db.executemany("INSERT OR IGNORE INTO friends VALUES (?)", [(u,) for u in user_ids])

    def inject_response(
        self, plurk_id: int, user_id: int, nick: str, content: str, posted: datetime | None = None
    ) -> int:
        """Balasan pemain tiruan. `posted` default = jam FakePlurk sekarang."""
        waktu = ke_wib(posted).isoformat() if posted else self._waktu()
        return self._tambah(plurk_id, user_id, nick, content, waktu)

    def plurk(self, plurk_id: int) -> tuple[str, str] | None:
        """(content, posted) plurk, atau None."""
        return self.db.execute("SELECT content, posted FROM plurks WHERE id = ?", (plurk_id,)).fetchone()

    def jumlah_plurk(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM plurks").fetchone()[0]

    def semua_balasan(self, plurk_id: int) -> list[PlurkResponse]:
        return self.get_responses(plurk_id, 0)

    def tutup(self) -> None:
        self.db.close()
