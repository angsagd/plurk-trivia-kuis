"""Alat uji tahap 4 berjalan dari awal sampai akhir terhadap Plurk tiruan (tanpa jaringan)."""

from datetime import UTC, datetime
from email.utils import format_datetime

from app.config import Settings
from app.plurk.real import RealPlurk
from app.plurk.uji import jalankan


class Jawaban:
    def __init__(self, status, isi):
        self.status_code, self._isi, self.text = status, isi, str(isi)

    def json(self):
        return self._isi


class PlurkTiruan:
    """Meniru endpoint secukupnya: ID balasan naik, from_response = offset, batas 360, isi kembar ditolak."""

    def __init__(self):
        self.balasan: list[dict] = []

    def post(self, url, data, timeout):
        path = url.split("plurk.com", 1)[1]
        waktu = format_datetime(datetime(2026, 11, 30, 5, 0, tzinfo=UTC), usegmt=True)
        if path == "/APP/Users/me":
            return Jawaban(200, {"id": 1, "nick_name": "kuisbot"})
        if path == "/APP/Timeline/plurkAdd":
            return Jawaban(200, {"plurk_id": 99, "qualifier": data["qualifier"]})
        if path == "/APP/Timeline/getPlurk":
            return Jawaban(200, {"plurk": {"qualifier": ":", "limited_to": "|7|"}})
        if path == "/APP/Responses/responseAdd":
            if len(data["content"]) > 360:
                return Jawaban(400, {"error_text": "Invalid data"})
            if self.balasan and self.balasan[-1]["content_raw"] == data["content"]:
                return Jawaban(400, {"error_text": "anti-flood-same-content"})
            r = {"id": len(self.balasan) + 1, "user_id": 1, "content_raw": data["content"],
                 "content": data["content"], "posted": waktu}  # fmt: skip
            self.balasan.append(r)
            return Jawaban(200, r)
        if path == "/APP/Responses/get":
            mulai = int(data.get("from_response", 0))
            isi = self.balasan[mulai:]
            if data.get("count"):
                isi = isi[: int(data["count"])]
            return Jawaban(200, {"responses": isi, "friends": {"1": {"nick_name": "kuisbot"}}})
        if path in ("/APP/Alerts/getActive", "/APP/Alerts/getHistory"):
            return Jawaban(200, [{"type": "mentioned", "plurk_id": 5, "response_id": None, "from_user": {}}])
        if path == "/APP/Timeline/getPlurks":
            return Jawaban(200, {"plurks": [], "plurk_users": {}})
        if path == "/APP/Polling/getUnreadCount":
            return Jawaban(200, {"all": 0, "my": 0})
        if path == "/APP/FriendsFans/getFriendsByOffset":
            return Jawaban(200, [{"id": 7, "nick_name": "admin"}])
        return Jawaban(400, {"error_text": "tidak dikenal"})


def test_uji_plurk_menghasilkan_temuan(capsys):
    plurk = RealPlurk(Settings(), session=PlurkTiruan())
    lap = jalankan(plurk, [7], jeda=0, tidur=lambda _: None)
    t = lap.temuan
    assert t["id_naik_sesuai_urutan_kirim"] == "True"
    assert t["from_response"].startswith("OFFSET")
    assert t["count_didukung"] == "True"
    assert t["clue_=_spasi"] == "utuh" and t["spasi_ganda_raw_utuh"] == "True"
    assert t["panjang_360"].startswith("diterima") and t["panjang_361"].startswith("ditolak")
    assert t["isi_sama_berturut"].startswith("AntiFlood")
    assert "mentioned" in t["/APP/Alerts/getActive"]
    assert t["getFriendsByOffset"].startswith("1 teman")
    assert "Selesai." in capsys.readouterr().out
