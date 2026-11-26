FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Jakarta \
    RUFF_CACHE_DIR=/tmp/ruff-cache

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

# Pengguna non-root; folder data dibuat lebih dulu agar volume baru ikut dimiliki 'app'.
RUN useradd --uid 1000 --create-home app \
 && mkdir -p /app/data \
 && chown app:app /app/data

COPY --chown=app:app . .

USER app
EXPOSE 8000
CMD ["uvicorn", "app.admin.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
