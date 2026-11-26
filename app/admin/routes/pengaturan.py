"""Kontrol & pengaturan: mode uji, clue, jadwal, aturan, rumus skor, template pesan."""

import uuid
from datetime import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.admin.deps import audit, get_db, jam_nyata, kembali, render, templates, wajib_login
from app.bot.messages import CONTOH_ISIAN, LABEL_TEMPLATE, TEMPLATE_BAWAAN, _Aman
from app.bot.outbox import antre
from app.bot.pengaturan import muat_pengaturan, simpan_pengaturan
from app.core import clues
from app.core.schedule import NAMA_HARI
from app.core.scoring import RUMUS, hitung_skor
from app.models import Template

router = APIRouter(dependencies=[Depends(wajib_login)])
CONTOH_JAWABAN = "MOHAMMAD HATTA"
LABEL_PEMISAH = {" ": "spasi", " / ": "garis miring ( / )"}


def _pratinjau_clue(karakter: str, pemisah: str) -> tuple[str, str]:
    try:
        return clues.clue2(CONTOH_JAWABAN, karakter, pemisah), clues.clue3(CONTOH_JAWABAN, karakter, pemisah)
    except ValueError:
        return "", ""


@router.get("/pengaturan", response_class=HTMLResponse)
def halaman(request: Request, template: str = "sesi_baru", db: Session = Depends(get_db)):
    p = muat_pengaturan(db)
    key = template if template in TEMPLATE_BAWAAN else "sesi_baru"
    t = db.get(Template, key)
    isi = t.body if t else TEMPLATE_BAWAAN[key]
    jam = p.jadwal.jam_sesi
    return render(
        request, db, "pengaturan.html", "pengaturan",
        p=p, clue=_pratinjau_clue(p.karakter_pengganti, p.pemisah_kata),
        karakter=clues.KARAKTER_PENGGANTI, pemisah=LABEL_PEMISAH, nama_hari=NAMA_HARI,
        jam_mulai=jam[0].strftime("%H:%M") if jam else "12:00",
        jam_selesai=_hhmm(min(_menit(jam[-1]) + _interval(jam), 23 * 60 + 59)) if jam else "22:00",
        interval=_interval(jam),
        rumus=list(RUMUS), contoh_skor=[hitung_skor("SOEKARNO", f, p.rumus_skor) for f in range(4)],
        label_template=LABEL_TEMPLATE, key=key, isi=isi, diubah=t is not None,
        pratinjau=_render_contoh(isi),
    )  # fmt: skip


def _menit(t: time) -> int:
    return t.hour * 60 + t.minute


def _hhmm(menit: int) -> str:
    return f"{menit // 60:02d}:{menit % 60:02d}"


def _interval(jam: list[time]) -> int:
    """Jarak antar sesi dalam menit (bawaan 120)."""
    return _menit(jam[1]) - _menit(jam[0]) if len(jam) >= 2 else 120


def _render_contoh(isi: str) -> str:
    try:
        return isi.format_map(_Aman(CONTOH_ISIAN))
    except (ValueError, IndexError):
        return "⚠ Format kurung kurawal { } tidak valid."


@router.get("/pengaturan/pratinjau-clue", response_class=HTMLResponse)
def pratinjau_clue(request: Request, karakter: str = "=", pemisah: str = " "):
    c2, c3 = _pratinjau_clue(karakter, pemisah)
    return templates.TemplateResponse(request, "_clue.html", {"clue": (c2, c3)})


@router.get("/pengaturan/pratinjau-template", response_class=HTMLResponse)
def pratinjau_template(request: Request, isi: str = "", db: Session = Depends(get_db)):
    p = muat_pengaturan(db)
    teks = _render_contoh(isi)
    return templates.TemplateResponse(request, "_pratinjau.html", {"teks": teks, "batas": p.batas_teks})


@router.post("/pengaturan/mode-uji")
def mode_uji(aktif: str = Form(""), akun: str = Form(""), db: Session = Depends(get_db)):
    try:
        ids = [int(x) for x in akun.replace(" ", "").split(",") if x]
    except ValueError:
        return kembali("/pengaturan", err="ID akun Plurk harus angka, dipisah koma.")
    if aktif and not ids:
        return kembali("/pengaturan", err="Isi ID akun Plurk admin sebelum mengaktifkan mode uji.")
    simpan_pengaturan(db, jam_nyata(), mode_uji=bool(aktif), mode_uji_limited_to=ids)
    audit(db, "mode_uji", aktif=bool(aktif), akun=ids)
    db.commit()
    return kembali(
        "/pengaturan", ok="Mode uji " + ("aktif: sesi baru hanya terlihat akun admin." if aktif else "mati.")
    )


@router.post("/pengaturan/clue")
def simpan_clue(karakter: str = Form(...), pemisah: str = Form(...), db: Session = Depends(get_db)):
    if karakter not in clues.KARAKTER_PENGGANTI or pemisah not in clues.PEMISAH_KATA:
        return kembali("/pengaturan", err="Pilihan karakter/pemisah tidak dikenal.")
    simpan_pengaturan(db, jam_nyata(), karakter_pengganti=karakter, pemisah_kata=pemisah)
    audit(db, "pengaturan_clue", karakter=karakter, pemisah=pemisah)
    db.commit()
    return kembali("/pengaturan", ok="Tampilan clue disimpan.")


def _kirim_uji(db: Session, isi: str) -> str | None:
    p = muat_pengaturan(db)
    if not p.mode_uji_limited_to:
        return "Isi ID akun Plurk admin (bagian Mode uji) dulu."
    if len(isi) > p.batas_teks:
        return f"Teks {len(isi)} karakter, melebihi batas {p.batas_teks}."
    antre(
        db, f"uji:{uuid.uuid4().hex}", isi, jam_nyata(), kind="plurk", limited_to=list(p.mode_uji_limited_to)
    )
    audit(db, "kirim_uji_privat", isi=isi[:200])
    db.commit()
    return None


@router.post("/pengaturan/uji-clue")
def uji_clue(db: Session = Depends(get_db)):
    p = muat_pengaturan(db)
    c2, c3 = _pratinjau_clue(p.karakter_pengganti, p.pemisah_kata)
    err = _kirim_uji(db, f"[Uji tampilan clue] {CONTOH_JAWABAN}\n💡 Clue 2: {c2}\n💡 Clue 3: {c3}")
    return kembali(
        "/pengaturan", err=err, ok=None if err else "Plurk uji privat diantre; terkirim pada tick berikutnya."
    )


@router.post("/pengaturan/jadwal")
def simpan_jadwal(
    mulai: str = Form(...),
    selesai: str = Form(...),
    interval: int = Form(...),
    hari: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    try:
        t0, t1 = time.fromisoformat(mulai), time.fromisoformat(selesai)
    except ValueError:
        return kembali("/pengaturan", err="Format jam harus HH:MM.")
    if not 30 <= interval <= 360 or t1 <= t0:
        return kembali("/pengaturan", err="Jam selesai harus setelah jam mulai; jarak sesi 30-360 menit.")
    if not hari or any(h not in range(7) for h in hari):
        return kembali("/pengaturan", err="Pilih minimal satu hari aktif.")
    jam = [_hhmm(m) for m in range(_menit(t0), _menit(t1), interval)]
    simpan_pengaturan(db, jam_nyata(), hari_aktif=sorted(set(hari)), jam_sesi=jam)
    audit(db, "pengaturan_jadwal", hari_aktif=sorted(set(hari)), jam_sesi=jam)
    db.commit()
    return kembali("/pengaturan", ok=f"Jadwal disimpan: {len(jam)} sesi per hari aktif ({', '.join(jam)}).")


ATURAN = {  # nama: (min, maks)
    "maks_soal": (1, 10),
    "umur_hold_menit": (10, 240),
    "maks_karakter_balasan": (10, 200),
    "maks_per_fase": (1, 10),
    "maks_posting_per_tick": (1, 5),
    "batas_teks": (100, 360),
}


@router.post("/pengaturan/aturan")
async def simpan_aturan(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    nilai: dict[str, object] = {}
    for nama, (lo, hi) in ATURAN.items():
        try:
            v = int(str(form.get(nama, "")))
        except ValueError:
            return kembali("/pengaturan", err=f"{nama} harus angka.")
        if not lo <= v <= hi:
            return kembali("/pengaturan", err=f"{nama} harus {lo}-{hi}.")
        nilai[nama] = v
    try:
        jeda = float(str(form.get("jeda_posting_detik", "")))
    except ValueError:
        return kembali("/pengaturan", err="Jeda posting harus angka.")
    if not 0 <= jeda <= 10:
        return kembali("/pengaturan", err="Jeda posting 0-10 detik.")
    nilai["jeda_posting_detik"] = jeda
    simpan_pengaturan(db, jam_nyata(), **nilai)
    audit(db, "pengaturan_aturan", **nilai)
    db.commit()
    return kembali("/pengaturan", ok="Aturan permainan disimpan; berlaku pada tick berikutnya.")


@router.post("/pengaturan/rumus")
def simpan_rumus(rumus: str = Form(...), db: Session = Depends(get_db)):
    if rumus not in RUMUS:
        return kembali("/pengaturan", err="Rumus skor tidak dikenal.")
    simpan_pengaturan(db, jam_nyata(), rumus_skor=rumus)
    audit(db, "pengaturan_rumus", rumus=rumus)
    db.commit()
    return kembali("/pengaturan", ok=f"Rumus skor: {rumus}.")


@router.post("/pengaturan/template")
def simpan_template(
    key: str = Form(...), isi: str = Form(...), aksi: str = Form("simpan"), db: Session = Depends(get_db)
):
    if key not in TEMPLATE_BAWAAN:
        return kembali("/pengaturan", err="Template tidak dikenal.")
    tujuan = f"/pengaturan?template={key}"
    t = db.get(Template, key)
    if aksi == "reset":
        if t is not None:
            db.delete(t)
        audit(db, "template_reset", key=key)
        db.commit()
        return kembali(tujuan, ok="Template dikembalikan ke teks bawaan.")
    isi = isi.replace("\r\n", "\n").strip()
    p = muat_pengaturan(db)
    if not isi:
        return kembali(tujuan, err="Template tidak boleh kosong.")
    if _render_contoh(isi).startswith("⚠"):
        return kembali(tujuan, err="Format kurung kurawal { } tidak valid.")
    if len(_render_contoh(isi)) > p.batas_teks:
        return kembali(tujuan, err=f"Pratinjau melebihi {p.batas_teks} karakter.")
    if t is None:
        db.add(Template(key=key, body=isi, updated_at=jam_nyata()))
    else:
        t.body, t.updated_at = isi, jam_nyata()
    audit(db, "template_ubah", key=key)
    db.commit()
    return kembali(tujuan, ok="Template disimpan.")
