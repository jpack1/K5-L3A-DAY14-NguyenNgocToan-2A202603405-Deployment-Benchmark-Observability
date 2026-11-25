# ============================================================
# Production Dockerfile — multi-stage, slim, non-root, HEALTHCHECK
# Build: docker build -t day14-agent .   (chạy trong 06-lab-complete/)
# ============================================================

# ── Stage 1: builder — cài dependencies vào virtualenv riêng ──
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements trước để layer cài deps được cache khi chỉ sửa code
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime — chỉ copy venv + code, không có pip cache / build tools ──
FROM python:3.11-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health', timeout=3)" || exit 1

# exec → uvicorn thay thế sh và là PID 1, nhận trực tiếp SIGTERM từ `docker stop`; PORT do platform cấp
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
