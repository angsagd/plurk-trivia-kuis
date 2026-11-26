"""Uji perilaku Plurk API asli (tahap 4) lewat satu plurk PRIVAT (limited_to).

Membuktikan asumsi yang belum pasti: urutan ID balasan, arti `from_response`, batas panjang teks,
tampilan clue (karakter pengganti, spasi ganda), qualifier ':', anti-flood isi sama,
cara membaca mention, dan daftar teman. Hanya mencetak struktur/jumlah, bukan isi milik orang lain.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core import clues
from app.plurk.client import AntiFlood, PlurkError, tautan_plurk
from app.plurk.real import RealPlurk

CONTOH_JAWABAN = "MOHAMMAD HATTA"


@dataclass
class Laporan:
    baris: list[str] = field(default_factory=list)
    temuan: dict[str, str] = field(default_factory=dict)

    def tulis(self, teks: str = "") -> None:
        self.baris.append(teks)
        print(teks, flush=True)

    def catat(self, kunci: str, nilai: str) -> None:
        self.temuan[kunci] = nilai
        self.tulis(f"  => {kunci}: {nilai}")

    def teks(self) -> str:
        return "\n".join(self.baris)


def jalankan(
    plurk: RealPlurk, untuk: list[int], jeda: float = 3.0, tidur: Callable[[float], None] = time.sleep
):
    lap = Laporan()
    panggil = plurk._panggil  # akses API mentah untuk penyelidikan

    def balas(pid: int, teks: str) -> int | None:
        tidur(jeda)
        try:
            return plurk.add_response(pid, teks, ":")
        except PlurkError as e:
            lap.tulis(f"  ! balasan ditolak: {e}")
            return None

    lap.tulis("# Uji Plurk API (tahap 4)")
    saya = plurk.whoami()
    lap.tulis(f"Akun bot: {saya.nick} (id {saya.id}); plurk privat untuk: {untuk}")

    lap.tulis("\n## 1. Plurk privat + qualifier ':'")
    pid = plurk.add_plurk("[Uji kuisbot] Plurk uji privat. Abaikan.", ":", limited_to=untuk)
    lap.catat("plurk_uji", tautan_plurk(pid))
    info = panggil("/APP/Timeline/getPlurk", plurk_id=pid)
    p = info.get("plurk", info)
    lap.catat("qualifier_tersimpan", repr(p.get("qualifier")))
    lap.catat("limited_to_tersimpan", repr(p.get("limited_to")))

    lap.tulis("\n## 2. Urutan ID balasan")
    ids = [balas(pid, f"uji urutan {i}") for i in range(1, 6)]
    ids_ok = [i for i in ids if i]
    lap.catat("id_naik_sesuai_urutan_kirim", str(ids_ok == sorted(ids_ok) and len(ids_ok) == 5))
    dibaca = plurk.get_responses(pid)
    urut = [r.content for r in dibaca if r.content.startswith("uji urutan")]
    lap.catat("urutan_terbaca", ", ".join(urut))

    lap.tulis("\n## 3. Arti from_response")
    mentah = panggil("/APP/Responses/get", plurk_id=pid, from_response=2)
    hasil = [int(r["id"]) for r in mentah.get("responses", [])]
    semua = sorted(r.id for r in dibaca)
    if hasil == semua[2:]:
        arti = "OFFSET (indeks balasan, mulai 0)"
    elif hasil == [i for i in semua if i > 2]:
        arti = "ID (balasan dengan ID > nilai)"
    else:
        arti = f"tidak jelas: dapat {hasil} dari {semua}"
    lap.catat("from_response", arti)
    mentah = panggil("/APP/Responses/get", plurk_id=pid, from_response=0, count=2)
    lap.catat("count_didukung", str(len(mentah.get("responses", [])) == 2))

    lap.tulis("\n## 4. Tampilan clue (dibandingkan dengan teks yang dibaca kembali)")
    for kar in clues.KARAKTER_PENGGANTI:
        for pem in clues.PEMISAH_KATA:
            c2, c3 = clues.clue2(CONTOH_JAWABAN, kar, pem), clues.clue3(CONTOH_JAWABAN, kar, pem)
            teks = f"Clue [{kar}|{pem.strip() or 'spasi'}] {c2} · {c3}"
            rid = balas(pid, teks)
            if rid is None:
                lap.catat(f"clue_{kar}_{pem.strip() or 'spasi'}", "DITOLAK")
                continue
            r = next((x for x in plurk.get_responses(pid) if x.id == rid), None)
            mentah = panggil("/APP/Responses/get", plurk_id=pid, from_response=0)
            html = next(
                (x.get("content", "") for x in mentah.get("responses", []) if int(x["id"]) == rid), ""
            )
            sama = r is not None and r.content == teks
            lap.catat(
                f"clue_{kar}_{pem.strip() or 'spasi'}",
                "utuh" if sama else f"BERUBAH raw={r.content if r else None!r}",
            )
            lap.tulis(f"     html: {html[:160]}")
    rid = balas(pid, "spasi  ganda   di sini")
    if rid:
        r = next((x for x in plurk.get_responses(pid) if x.id == rid), None)
        lap.catat("spasi_ganda_raw_utuh", str(r is not None and r.content == "spasi  ganda   di sini"))

    lap.tulis("\n## 5. Batas panjang teks balasan")
    for n in (300, 360, 361, 400, 500):
        tidur(jeda)
        try:
            rid = plurk.add_response(pid, ("panjang " * 80)[: n - 4] + f" {n:03d}", ":")
            r = next((x for x in plurk.get_responses(pid) if x.id == rid), None)
            lap.catat(f"panjang_{n}", f"diterima, terbaca {len(r.content) if r else '?'} karakter")
        except PlurkError as e:
            lap.catat(f"panjang_{n}", f"ditolak: {e}")

    lap.tulis("\n## 6. Anti-flood isi sama berturut-turut")
    balas(pid, "isi kembar")
    tidur(jeda)
    try:
        plurk.add_response(pid, "isi kembar", ":")
        lap.catat("isi_sama_berturut", "DITERIMA (tidak ada anti-flood)")
    except AntiFlood as e:
        lap.catat("isi_sama_berturut", f"AntiFlood: {e}")
    except PlurkError as e:
        lap.catat("isi_sama_berturut", f"error lain: {e}")

    lap.tulis("\n## 7. Membaca mention (hanya struktur, tanpa isi)")
    for path, params in (
        ("/APP/Alerts/getActive", {}),
        ("/APP/Alerts/getHistory", {}),
        ("/APP/Timeline/getPlurks", {"filter": "mentioned", "limit": 5}),
        ("/APP/Polling/getUnreadCount", {}),
    ):
        try:
            isi = panggil(path, **params)
            if isinstance(isi, list):
                jenis = sorted({str(a.get("type")) for a in isi if isinstance(a, dict)})
                kunci = sorted(isi[0].keys()) if isi and isinstance(isi[0], dict) else []
                lap.catat(path, f"list {len(isi)} item; type={jenis}; kunci={kunci}")
            else:
                ringkas = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in isi.items()}
                lap.catat(path, json.dumps(ringkas)[:300])
        except PlurkError as e:
            lap.catat(path, f"error: {e}")

    lap.tulis("\n## 8. Daftar teman")
    try:
        teman = panggil("/APP/FriendsFans/getFriendsByOffset", user_id=saya.id, offset=0, limit=10)
        lap.catat(
            "getFriendsByOffset",
            f"{len(teman)} teman (maks 10 per halaman); kunci={sorted(teman[0]) if teman else []}",
        )
    except PlurkError as e:
        lap.catat("getFriendsByOffset", f"error: {e}")

    lap.tulis("\nSelesai. Plurk uji bisa dihapus manual dari akun bot bila perlu.")
    return lap
