"""Tes RealPlurk tanpa jaringan: sesi HTTP palsu merekam panggilan dan memberi jawaban buatan."""

import json
from datetime import datetime

import pytest
from requests import ConnectionError as RequestsConnectionError

from app import cli
from app.clock import WIB
from app.config import Settings
from app.plurk import buat_plurk
from app.plurk.client import AntiFlood, PlurkError, TokenDitolak
from app.plurk.real import BASE_URL, RealPlurk

KREDENSIAL = {
    "plurk_consumer_key": "ck",
    "plurk_consumer_secret": "cs",
    "plurk_access_token": "at",
    "plurk_access_secret": "as",
}


class Jawaban:
    def __init__(self, status: int, isi):
        self.status_code = status
        self._isi = isi
        self.text = isi if isinstance(isi, str) else json.dumps(isi)

    def json(self):
        if isinstance(self._isi, str):
            raise ValueError("bukan json")
        return self._isi


class SesiPalsu:
    def __init__(self, *jawaban):
        self.jawaban = list(jawaban)
        self.panggilan: list[tuple[str, dict]] = []

    def post(self, url, data, timeout):
        self.panggilan.append((url.removeprefix(BASE_URL), data))
        j = self.jawaban.pop(0)
        if isinstance(j, Exception):
            raise j
        return j


def plurk(*jawaban) -> tuple[RealPlurk, SesiPalsu]:
    sesi = SesiPalsu(*jawaban)
    return RealPlurk(Settings(**KREDENSIAL), session=sesi), sesi


def test_kredensial_kosong_ditolak_dengan_pesan_jelas():
    with pytest.raises(ValueError, match="PLURK_ACCESS_TOKEN, PLURK_ACCESS_SECRET"):
        RealPlurk(Settings(plurk_consumer_key="ck", plurk_consumer_secret="cs"))


def test_buat_plurk_mode_real_memakai_oauth():
    p = buat_plurk(Settings(plurk_mode="real", **KREDENSIAL), clock=None)
    assert isinstance(p, RealPlurk)


def test_whoami_dicache():
    p, sesi = plurk(Jawaban(200, {"id": 42, "nick_name": "kuisbot", "display_name": "Kuis"}))
    assert p.whoami().id == 42 and p.whoami().nick == "kuisbot"
    assert sesi.panggilan == [("/APP/Users/me", {})]


def test_add_plurk_parameter_dan_limited_to_json():
    p, sesi = plurk(Jawaban(200, {"plurk_id": 1234, "content": "x"}))
    assert p.add_plurk("Halo", ":", limited_to=[7, 8]) == 1234
    assert sesi.panggilan == [
        ("/APP/Timeline/plurkAdd", {"content": "Halo", "qualifier": ":", "limited_to": "[7, 8]"})
    ]


def test_add_plurk_tanpa_limited_to_tidak_mengirim_parameter_kosong():
    p, sesi = plurk(Jawaban(200, {"plurk_id": 1}))
    p.add_plurk("Halo")
    assert sesi.panggilan[0][1] == {"content": "Halo", "qualifier": ":"}


def test_add_response_mengembalikan_id():
    p, sesi = plurk(Jawaban(200, {"id": 555, "content": "x"}))
    assert p.add_response(1234, "Soal #1", ":") == 555
    assert sesi.panggilan == [
        ("/APP/Responses/responseAdd", {"plurk_id": 1234, "content": "Soal #1", "qualifier": ":"})
    ]


def test_get_responses_saring_urut_nick_dan_waktu_wib():
    isi = {
        "friends": {"7": {"nick_name": "andi"}, "8": {"nick_name": "budi"}},
        "responses_seen": 0,
        "responses": [
            {"id": 30, "user_id": 8, "content": "<b>bali</b>", "content_raw": "**bali**",
             "posted": "Mon, 30 Nov 2026 05:01:30 GMT"},
            {"id": 10, "user_id": 7, "content": "lama", "content_raw": "lama",
             "posted": "Mon, 30 Nov 2026 05:00:10 GMT"},
            {"id": 20, "user_id": 99999, "handle": "anon-kucing", "content": "siap", "content_raw": "siap",
             "posted": "Mon, 30 Nov 2026 05:00:50 GMT"},
        ],
    }  # fmt: skip
    p, sesi = plurk(Jawaban(200, isi))
    hasil = p.get_responses(1234, setelah_id=10)
    assert [(r.id, r.nick, r.content) for r in hasil] == [
        (20, "anon-kucing", "siap"),
        (30, "budi", "**bali**"),
    ]
    assert hasil[1].posted == datetime(2026, 11, 30, 12, 1, 30, tzinfo=WIB)
    assert sesi.panggilan == [("/APP/Responses/get", {"plurk_id": 1234, "from_response": 0})]


def test_accept_friends():
    p, sesi = plurk(Jawaban(200, {"success_text": "ok"}))
    p.accept_friends()
    assert sesi.panggilan == [("/APP/Alerts/addAllAsFriends", {})]


@pytest.mark.parametrize(
    "jawaban, error",
    [
        (Jawaban(400, {"error_text": "anti-flood-same-content"}), AntiFlood),
        (Jawaban(400, {"error_text": "anti-flood-too-many-new"}), AntiFlood),
        (Jawaban(401, {"error_text": "40106:invalid access token"}), TokenDitolak),
        (Jawaban(400, {"error_text": "invalid access token"}), TokenDitolak),
        (Jawaban(401, "<html>Unauthorized</html>"), TokenDitolak),
        (Jawaban(400, {"error_text": "Plurk not found"}), PlurkError),
        (Jawaban(500, "<html>error</html>"), PlurkError),
        (Jawaban(200, "bukan json"), PlurkError),
        (RequestsConnectionError("putus"), PlurkError),
    ],
)
def test_pemetaan_error(jawaban, error):
    p, _ = plurk(jawaban)
    with pytest.raises(error) as e:
        p.add_response(1, "x")
    assert type(e.value) is error


def test_cli_cek_plurk_tanpa_kredensial(capsys):
    assert cli.main(["cek-plurk"]) == 1
    assert "Kredensial Plurk belum diisi" in capsys.readouterr().out
