"""Impor satu file topik ke database. Dipakai CLI `seed` dan (tahap 5) unggah lewat admin.

Fungsi ini hanya flush, tidak commit: pemanggil memutuskan simpan (commit) atau batal (rollback),
sehingga admin bisa menampilkan pratinjau dulu."""

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.matching import jumlah_huruf
from app.core.validator import HasilValidasi, TopikAda, kunci_topik, rencana_unggah, topik_mirip, validasi_isi
from app.models import Question, Topic


@dataclass
class LaporanImpor:
    topik_id: int
    nomor: str
    nama: str
    topik_baru: bool
    validasi: HasilValidasi
    soal_baru: int = 0
    diperbarui: int = 0
    tetap: int = 0
    dinonaktifkan: int = 0
    duplikat_di_file: int = 0
    mirip_dengan: str | None = None  # nama topik lain yang memuat > 50% soal file ini

    def ringkasan(self) -> str:
        jenis = "topik baru" if self.topik_baru else "diperbarui"
        teks = (
            f"[{self.nomor}] {self.nama} ({jenis}): {len(self.validasi.valid)} soal valid, "
            f"{self.validasi.baris_error} baris error | baru {self.soal_baru}, diperbarui {self.diperbarui}, "
            f"tetap {self.tetap}, dinonaktifkan {self.dinonaktifkan}"
        )
        if self.duplikat_di_file:
            teks += f", duplikat di file {self.duplikat_di_file}"
        if self.mirip_dengan:
            teks += f"\n  PERINGATAN: lebih dari separuh soal sudah ada di topik '{self.mirip_dengan}'"
            teks += " (mungkin topik itu yang diganti nama)"
        return teks


def impor_topik(db: Session, nama_file: str, teks: str, now: datetime) -> LaporanImpor:
    """Validasi + simpan (flush) satu file topik. ValidasiGagal bila nama file/nomor ditolak.

    - Topik bernama sama (tanpa beda huruf besar/kecil) diperbarui; selain itu topik baru.
    - Soal dikenali lewat text_hash: soal yang ada diperbarui clue/jawabannya tanpa menghapus riwayat.
    - Soal yang tidak ada lagi di file dinonaktifkan (tidak dihapus).
    - Baris yang error dilewati; soal yang sama dua kali di file hanya disimpan sekali.
    """
    hasil = validasi_isi(teks)
    semua = db.scalars(select(Topic)).all()
    rencana = rencana_unggah(nama_file, [TopikAda(t.id, t.number, t.name) for t in semua])

    mirip = None
    if rencana.topik_id is None:
        per_topik: dict[int, set[str]] = defaultdict(set)
        for tid, h in db.execute(select(Question.topic_id, Question.text_hash)):
            per_topik[tid].add(h)
        mirip_id = topik_mirip((v.text_hash for v in hasil.valid), per_topik)
        mirip = next((t.name for t in semua if t.id == mirip_id), None)
        topik = Topic(
            number=rencana.nomor,
            name=rencana.nama,
            name_key=kunci_topik(rencana.nama),
            filename=os.path.basename(nama_file),
            is_active=True,
            cycle=1,
            created_at=now,
            updated_at=now,
        )
        db.add(topik)
        db.flush()
    else:
        topik = db.get_one(Topic, rencana.topik_id)
        topik.filename = os.path.basename(nama_file)
        topik.updated_at = now

    lap = LaporanImpor(
        topik.id, topik.number, topik.name, rencana.topik_id is None, hasil, mirip_dengan=mirip
    )
    ada = {q.text_hash: q for q in db.scalars(select(Question).where(Question.topic_id == topik.id))}
    terlihat: set[str] = set()

    for v in hasil.valid:
        if v.text_hash in terlihat:
            lap.duplikat_di_file += 1
            continue
        terlihat.add(v.text_hash)
        q = ada.get(v.text_hash)
        if q is None:
            db.add(
                Question(
                    topic_id=topik.id,
                    text_hash=v.text_hash,
                    soal=v.soal,
                    clue=v.clue,
                    jawaban=v.jawaban,
                    letters=jumlah_huruf(v.jawaban),
                    is_active=True,
                    used_cycle=0,
                    times_used=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            lap.soal_baru += 1
        elif (q.soal, q.clue, q.jawaban, q.is_active) != (v.soal, v.clue, v.jawaban, True):
            q.soal, q.clue, q.jawaban, q.is_active = v.soal, v.clue, v.jawaban, True
            q.letters = jumlah_huruf(v.jawaban)
            q.updated_at = now
            lap.diperbarui += 1
        else:
            lap.tetap += 1

    for h, q in ada.items():
        if h not in terlihat and q.is_active:
            q.is_active = False
            q.updated_at = now
            lap.dinonaktifkan += 1

    db.flush()
    return lap
