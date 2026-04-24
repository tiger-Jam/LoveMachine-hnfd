# 花札こいこい - Web サーバ用 Docker image
#
# ビルド:   docker build -t hanafuda-koikoi .
# 実行:     docker run --rm -p 8800:8800 -v "$PWD/kifu:/app/kifu" hanafuda-koikoi
# compose:  docker compose up -d

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Serve-only deps — engine.py imports numpy. RL training deps (torch/
# stable-baselines3/etc.) are intentionally not installed here to keep
# the image small.
COPY requirements-serve.txt ./
RUN pip install -r requirements-serve.txt

# App source. kifu/ and models/ are mounted as volumes at run time.
COPY core.py engine.py web.py ./
COPY static ./static
RUN mkdir -p /app/kifu /app/models

# Run as a non-root user for hygiene.
RUN useradd --create-home --uid 1000 app \
 && chown -R app:app /app
USER app

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request, sys; \
urllib.request.urlopen('http://127.0.0.1:8800/api/cards', timeout=2); sys.exit(0)" \
  || exit 1

CMD ["python3", "web.py"]
