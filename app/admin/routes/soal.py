"""Bank soal: unggah topik (validasi -> pratinjau -> simpan), ganti nama, aktif/nonaktif, cari soal."""

import base64
import csv
import io

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.admin.deps import audit, get_db, jam_nyata, kembali, render, wajib_login
from app.admin.query import stok_topik
from app.bank_soal import impor_topik
from app.core.selection import bentrok
from app.core.validator import TopikAda, ValidasiGagal, kunci_topik, validasi_ganti_nama
from app.models import Question, SessionQuestion, Topic

router = APIRouter(dependencies=[Depends(wajib_login)])
MAKS_UKURAN = 2 * 1024 * 1024


def _halaman(request: Request, db: Session, **ctx):
    stok = stok_topik(db)
    cari, topik = request.query_params.get("cari", ""), request.query_params.get("topik", "")
    soal = []
    if cari or topik:
        q = select(Question).order_by(Question.id).limit(100)
        if cari:
            pola = f"%{cari}%"
            q = q.where(
                or_(Question.soal.ilike(pola), Question.clue.ilike(pola), Question.jawaban.ilike(pola))
            )
        if topik.isdigit():
            q = q.where(Question.topic_id == int(topik))
        soal = db.scalars(q).all()
    riwayat = {}
    for s in soal:
        sq = db.scalars(select(SessionQuestion).where(SessionQuestion.question_id == s.id)).all()
        riwayat[s.id] = sq
    return render(
        request, db, "soal.html", "soal",
        stok=stok, total=sum(s.total for s in stok), cari=cari, topik=topik, soal=soal, riwayat=riwayat,
        ganti=request.query_params.get("ganti", ""), **ctx,
    )  # fmt: skip


@router.get("/soal", response_class=HTMLResponse)
def halaman(request: Request, db: Session = Depends(get_db)):
    return _halaman(request, db)


def _pratinjau(request: Request, db: Session, nama_file: str, teks: str):
    """Jalankan impor di dalam transaksi lalu batalkan: hasilnya ditampilkan sebagai pratinjau."""
    try:
        lap = impor_topik(db, nama_file, teks, jam_nyata())
    except ValidasiGagal as e:
        db.rollback()
        return _halaman(request, db, err_unggah=str(e), nama_file=nama_file)
    mirip_id = None
    if lap.mirip_dengan:
        mirip_id = db.scalar(select(Topic.id).where(Topic.name == lap.mirip_dengan))
    valid = lap.validasi.valid
    pasangan = 0
    if len(valid) <= 1500:
        from app.core.selection import KandidatSoal

        k = [KandidatSoal(i, 0, v.soal, v.clue, v.jawaban) for i, v in enumerate(valid)]
        pasangan = sum(
            1 for i, a in enumerate(k) for b in k[i + 1 :] if a.jawaban != b.jawaban and bentrok(a, b)
        )
    db.rollback()
    return _halaman(
        request,
        db,
        lap=lap,
        nama_file=nama_file,
        isi_b64=base64.b64encode(teks.encode("utf-8")).decode(),
        mirip_id=mirip_id,
        pasangan_bocor=pasangan,
        panjang_soal=max((len(v.soal) for v in valid), default=0),
        rentang_huruf=(
            min((len(v.jawaban.replace(" ", "")) for v in valid), default=0),
            max((len(v.jawaban.replace(" ", "")) for v in valid), default=0),
        ),
    )


@router.post("/soal/unggah", response_class=HTMLResponse)
async def unggah(request: Request, berkas: UploadFile, db: Session = Depends(get_db)):
    data = await berkas.read(MAKS_UKURAN + 1)
    nama = (berkas.filename or "").rsplit("/", 1)[-1]
    if len(data) > MAKS_UKURAN:
        return _halaman(request, db, err_unggah="File terlalu besar (maks 2 MB).", nama_file=nama)
    try:
        teks = data.decode("utf-8")
    except UnicodeDecodeError:
        return _halaman(request, db, err_unggah="File harus berencoding UTF-8.", nama_file=nama)
    return _pratinjau(request, db, nama, teks)


def _isi(isi_b64: str) -> str:
    return base64.b64decode(isi_b64.encode()).decode("utf-8")


@router.post("/soal/simpan")
def simpan(nama_file: str = Form(...), isi_b64: str = Form(...), db: Session = Depends(get_db)):
    try:
        lap = impor_topik(db, nama_file, _isi(isi_b64), jam_nyata())
    except (ValidasiGagal, ValueError) as e:
        db.rollback()
        return kembali("/soal", err=str(e))
    audit(
        db, "unggah_topik", file=nama_file, topik=lap.nama, baru=lap.topik_baru, soal_baru=lap.soal_baru,
        diperbarui=lap.diperbarui, dinonaktifkan=lap.dinonaktifkan, error=lap.validasi.baris_error,
    )  # fmt: skip
    db.commit()
    return kembali("/soal", ok=f"Topik [{lap.nomor}] {lap.nama} tersimpan: {lap.soal_baru} soal baru, "
                   f"{lap.diperbarui} diperbarui, {lap.dinonaktifkan} dinonaktifkan.")  # fmt: skip


@router.post("/soal/laporan")
def laporan(nama_file: str = Form(...), isi_b64: str = Form(...)):
    from app.core.validator import validasi_isi

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["baris", "tingkat", "kode", "pesan", "isi"])
    for m in validasi_isi(_isi(isi_b64)).masalah:
        w.writerow([m.baris, m.tingkat, m.kode, m.pesan, m.isi])
    nama = nama_file.rsplit(".", 1)[0] + "_laporan.csv"
    return StreamingResponse(
        iter(["﻿" + buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )  # fmt: skip


@router.post("/soal/topik/{tid}/ganti-nama", response_class=HTMLResponse)
def ganti_nama(
    request: Request,
    tid: int,
    nama_file: str = Form(...),
    isi_b64: str = Form(""),
    db: Session = Depends(get_db),
):
    t = db.get(Topic, tid)
    if t is None:
        return kembali("/soal", err="Topik tidak ditemukan.")
    semua = [TopikAda(x.id, x.number, x.name) for x in db.scalars(select(Topic))]
    try:
        nomor, nama = validasi_ganti_nama(nama_file.strip(), TopikAda(t.id, t.number, t.name), semua)
    except ValidasiGagal as e:
        return kembali(f"/soal?ganti={tid}", err=str(e))
    lama = {"nomor": t.number, "nama": t.name, "file": t.filename}
    t.number, t.name, t.name_key, t.filename, t.updated_at = (
        nomor, nama, kunci_topik(nama), nama_file.strip(), jam_nyata()
    )  # fmt: skip
    audit(db, "ganti_nama_topik", lama=lama, baru={"nomor": nomor, "nama": nama, "file": nama_file.strip()})
    db.commit()
    if isi_b64:  # dari tawaran cek kemiripan: lanjutkan unggahan sebagai pembaruan topik ini
        return _pratinjau(request, db, nama_file.strip(), _isi(isi_b64))
    return kembali("/soal", ok=f"Topik diganti nama: [{lama['nomor']}] {lama['nama']} → [{nomor}] {nama}.")


@router.post("/soal/topik/{tid}/aktif")
def topik_aktif(tid: int, db: Session = Depends(get_db)):
    t = db.get(Topic, tid)
    if t is None:
        return kembali("/soal", err="Topik tidak ditemukan.")
    t.is_active = not t.is_active
    audit(db, "topik_aktif" if t.is_active else "topik_nonaktif", topik=t.name)
    db.commit()
    return kembali("/soal", ok=f"Topik {t.name} {'diaktifkan' if t.is_active else 'dinonaktifkan'}.")


@router.post("/soal/{qid}/aktif")
def soal_aktif(qid: int, kembali_ke: str = Form("/soal"), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if q is None:
        return kembali("/soal", err="Soal tidak ditemukan.")
    q.is_active = not q.is_active
    audit(db, "soal_aktif" if q.is_active else "soal_nonaktif", soal_id=q.id, jawaban=q.jawaban)
    db.commit()
    # Kembali ke hasil pencarian yang sama (hanya path internal /soal yang diizinkan).
    tujuan = kembali_ke if kembali_ke.startswith("/soal") and "//" not in kembali_ke else "/soal"
    return RedirectResponse(tujuan, status_code=303)
