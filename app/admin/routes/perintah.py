"""Perintah & easter egg: fitur aktif/mati, cooldown, batas global, kata kunci, template, kustom, log."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.admin.deps import audit, get_db, jam_nyata, kembali, render, sekarang, wajib_login
from app.admin.routes.pengaturan import _kirim_uji
from app.bot.messages import _Aman
from app.bot.pengaturan import muat_pengaturan, simpan_pengaturan
from app.core.commands import cek_kata_kunci, cek_respons_kustom, isian_template, rapikan_kata_kunci
from app.models import Command, CommandAlias, CommandRequest, CommandResponse, Player
from app.perintah import ALIAS_KHUSUS, ISIAN

router = APIRouter(dependencies=[Depends(wajib_login)])
JENIS = {"bawaan": "Bawaan", "statistik": "Statistik (tersembunyi)", "kustom": "Kustom (easter egg)"}
CONTOH = {
    "nama": "pemain_a",
    "rank": 7,
    "poin": 42,
    "selisih": 5,
    "rank_atas": 6,
    "sesi_berikutnya": "hari ini 16.00 WIB",
    "tautan_sesi": "",
    "top10": "1. pemain_a — 42\n2. pemain_b — 37",
    "daftar_bantuan": "jadwal, klasemen, rank",
    "rekor_mingguan": 184,
    "tercepat": "BALI (Soal)",
    "streak": 3,
    "total_benar": 57,
    "fase_favorit": "Clue 1",
}


def _alias(db: Session, cmd_id: int) -> list[str]:
    return list(
        db.scalars(
            select(CommandAlias.alias).where(CommandAlias.command_id == cmd_id).order_by(CommandAlias.id)
        )
    )


def _terpakai_lain(db: Session, kecuali: int | None) -> list[str]:
    kunci = [c.key for c in db.scalars(select(Command)) if c.id != kecuali]
    alias = [a.alias for a in db.scalars(select(CommandAlias)) if a.command_id != kecuali]
    return kunci + alias


@router.get("/perintah", response_class=HTMLResponse)
def halaman(request: Request, pilih: int = 0, db: Session = Depends(get_db)):
    p = muat_pengaturan(db)
    cmds = db.scalars(select(Command).order_by(Command.kind, Command.key)).all()
    dipilih = db.get(Command, pilih) if pilih else (cmds[0] if cmds else None)
    respons = (
        db.scalars(select(CommandResponse).where(CommandResponse.command_id == dipilih.id)).all()
        if dipilih
        else []
    )
    hari = sekarang(db).date()
    log = db.execute(
        select(CommandRequest, Player.nick, Command.key)
        .outerjoin(Player, Player.id == CommandRequest.player_id)
        .outerjoin(Command, Command.id == CommandRequest.command_id)
        .order_by(CommandRequest.id.desc())
        .limit(50)
    ).all()
    hari_ini = [r for r in log if r[0].received_at.date() == hari]
    pratinjau = ""
    if dipilih and dipilih.template:
        try:
            pratinjau = dipilih.template.format_map(_Aman(CONTOH))
        except ValueError:
            pratinjau = "⚠ Format kurung kurawal { } tidak valid."
    return render(
        request, db, "perintah.html", "perintah",
        p=p, cmds=[(c, _alias(db, c.id)) for c in cmds], dipilih=dipilih,
        alias_dipilih=_alias(db, dipilih.id) if dipilih else [], respons=respons, jenis=JENIS, isian=ISIAN,
        pratinjau=pratinjau, log=log, statistik={
            "mention": len(hari_ini), "dijawab": sum(1 for r in hari_ini if r[0].status == "dijawab"),
            "antre": db.scalar(select(func.count()).where(CommandRequest.status == "antre")) or 0,
        },
    )  # fmt: skip


@router.post("/perintah/fitur")
def fitur(
    aktif: str = Form(""),
    cooldown: int = Form(...),
    batas: int = Form(...),
    kedaluwarsa: int = Form(...),
    db: Session = Depends(get_db),
):
    if not (1 <= cooldown <= 1440 and 1 <= batas <= 200 and 5 <= kedaluwarsa <= 240):
        return kembali(
            "/perintah", err="Cooldown 1-1440 menit, batas global 1-200/jam, kedaluwarsa 5-240 menit."
        )
    nilai = {
        "perintah_aktif": bool(aktif),
        "perintah_cooldown_menit": cooldown,
        "perintah_batas_global_per_jam": batas,
        "perintah_kedaluwarsa_menit": kedaluwarsa,
    }
    simpan_pengaturan(db, jam_nyata(), **nilai)
    audit(db, "perintah_fitur", **nilai)
    db.commit()
    return kembali("/perintah", ok="Pengaturan fitur perintah disimpan.")


def _simpan_alias(db: Session, cmd: Command, teks: str) -> list[str]:
    """Ganti sinonim perintah; kembalikan daftar error (tidak menyimpan bila ada error)."""
    alias = [rapikan_kata_kunci(a) for a in teks.split(",") if a.strip()]
    khusus = [a for a, k in ALIAS_KHUSUS.items() if k == cmd.key]
    biasa = [a for a in alias if a not in khusus]
    err = cek_kata_kunci([cmd.key, *biasa], _terpakai_lain(db, cmd.id))
    if err:
        return err
    db.execute(delete(CommandAlias).where(CommandAlias.command_id == cmd.id))
    for a in dict.fromkeys(biasa + khusus):
        db.add(CommandAlias(alias=a, command_id=cmd.id))
    return []


@router.post("/perintah/{cid}")
def ubah(
    cid: int,
    alias: str = Form(""),
    aktif: str = Form(""),
    bantuan: str = Form(""),
    template: str = Form(""),
    db: Session = Depends(get_db),
):
    cmd = db.get(Command, cid)
    if cmd is None:
        return kembali("/perintah", err="Perintah tidak ditemukan.")
    tujuan = f"/perintah?pilih={cid}"
    err = _simpan_alias(db, cmd, alias)
    if cmd.kind != "kustom":
        template = template.replace("\r\n", "\n").strip()
        try:
            asing = isian_template(template) - set(ISIAN[cmd.kind].replace("{", "").replace("}", "").split())
        except ValueError:
            asing, err = set(), [*err, "kurung kurawal { } tidak seimbang"]
        if asing:
            err.append(f"isian tidak dikenal: {', '.join(sorted(asing))}")
        if not template:
            err.append("template kosong")
    if err:
        db.rollback()
        return kembali(tujuan, err="; ".join(err))
    cmd.enabled, cmd.show_in_help = bool(aktif), bool(bantuan)
    if cmd.kind != "kustom":
        cmd.template = template
    audit(db, "perintah_ubah", key=cmd.key, aktif=cmd.enabled, bantuan=cmd.show_in_help, alias=alias)
    db.commit()
    return kembali(tujuan, ok=f"Perintah '{cmd.key}' disimpan.")


@router.post("/perintah-kustom")
def tambah_kustom(
    key: str = Form(...),
    alias: str = Form(""),
    respons: str = Form(...),
    bantuan: str = Form(""),
    db: Session = Depends(get_db),
):
    key = rapikan_kata_kunci(key)
    biasa = [rapikan_kata_kunci(a) for a in alias.split(",") if a.strip()]
    err = cek_kata_kunci([key, *biasa], _terpakai_lain(db, None))
    err += cek_respons_kustom(respons.replace("\r\n", "\n").strip(), muat_pengaturan(db).batas_teks)
    if err:
        return kembali("/perintah", err="; ".join(err))
    cmd = Command(key=key, kind="kustom", enabled=True, show_in_help=bool(bantuan), template=None)
    db.add(cmd)
    db.flush()
    for a in dict.fromkeys(biasa):
        db.add(CommandAlias(alias=a, command_id=cmd.id))
    db.add(CommandResponse(command_id=cmd.id, body=respons.replace("\r\n", "\n").strip()))
    audit(db, "perintah_kustom_tambah", key=key, alias=biasa)
    db.commit()
    return kembali(f"/perintah?pilih={cmd.id}", ok=f"Kata kunci kustom '{key}' ditambahkan.")


@router.post("/perintah/{cid}/hapus")
def hapus(cid: int, db: Session = Depends(get_db)):
    cmd = db.get(Command, cid)
    if cmd is None or cmd.kind != "kustom":
        return kembali("/perintah", err="Hanya kata kunci kustom yang bisa dihapus.")
    db.execute(delete(CommandAlias).where(CommandAlias.command_id == cid))
    db.execute(delete(CommandResponse).where(CommandResponse.command_id == cid))
    for r in db.scalars(select(CommandRequest).where(CommandRequest.command_id == cid)):
        r.command_id = None
    db.delete(cmd)
    audit(db, "perintah_kustom_hapus", key=cmd.key)
    db.commit()
    return kembali("/perintah", ok=f"Kata kunci '{cmd.key}' dihapus.")


@router.post("/perintah/{cid}/respons")
def tambah_respons(cid: int, isi: str = Form(...), db: Session = Depends(get_db)):
    cmd = db.get(Command, cid)
    tujuan = f"/perintah?pilih={cid}"
    if cmd is None or cmd.kind != "kustom":
        return kembali("/perintah", err="Respons hanya untuk kata kunci kustom.")
    isi = isi.replace("\r\n", "\n").strip()
    err = cek_respons_kustom(isi, muat_pengaturan(db).batas_teks)
    if err:
        return kembali(tujuan, err="; ".join(err))
    db.add(CommandResponse(command_id=cid, body=isi))
    audit(db, "perintah_respons_tambah", key=cmd.key, isi=isi[:200])
    db.commit()
    return kembali(tujuan, ok="Respons ditambahkan.")


@router.post("/perintah/respons/{rid}/hapus")
def hapus_respons(rid: int, db: Session = Depends(get_db)):
    r = db.get(CommandResponse, rid)
    if r is None:
        return kembali("/perintah", err="Respons tidak ditemukan.")
    cid = r.command_id
    if db.scalar(select(func.count()).where(CommandResponse.command_id == cid)) <= 1:
        return kembali(
            f"/perintah?pilih={cid}", err="Minimal satu respons; hapus kata kuncinya bila tidak dipakai."
        )
    db.delete(r)
    audit(db, "perintah_respons_hapus", command_id=cid)
    db.commit()
    return kembali(f"/perintah?pilih={cid}", ok="Respons dihapus.")


@router.post("/perintah/{cid}/uji")
def uji(cid: int, db: Session = Depends(get_db)):
    cmd = db.get(Command, cid)
    if cmd is None:
        return kembali("/perintah", err="Perintah tidak ditemukan.")
    if cmd.kind == "kustom":
        r = db.scalars(select(CommandResponse).where(CommandResponse.command_id == cid)).first()
        teks = r.body if r else ""
    else:
        teks = cmd.template or ""
    teks = f"[Uji perintah {cmd.key}] " + teks.format_map(_Aman(CONTOH))
    err = _kirim_uji(db, teks)
    tujuan = f"/perintah?pilih={cid}"
    return kembali(
        tujuan, err=err, ok=None if err else "Plurk uji privat diantre; terkirim pada tick berikutnya."
    )
