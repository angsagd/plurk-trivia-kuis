"""Aplikasi admin web. Tahap 0: kerangka + /health. Halaman lengkap di tahap 5."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Plurk Trivia Kuis — Admin", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def beranda() -> str:
    return "<!doctype html><meta charset=utf-8><title>Admin Kuis</title><p>Admin belum dibuat (tahap 5).</p>"
