# 花札こいこい - Web サーバ用 Docker image
#
# ビルド:   docker build -t hanafuda-koikoi .
# 実行:     docker run --rm -p 8800:8800 -v "$PWD/kifu:/app/kifu" hanafuda-koikoi
# compose:  docker compose up -d --build
#
# 内訳:
#   stage builder : g++ + pybind11 で C++ KoikoiEngine 拡張モジュール
#                   (_koikoi_native*.so) をビルド
#   stage runtime : .so + Python 一式だけをコピーした軽量イメージ
#                   ビルド成果物はランタイムイメージに無いので最終サイズは
#                   pure-Python 版とほぼ同じ。

# =========================================
# 1. ビルドステージ
# =========================================
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ \
 && rm -rf /var/lib/apt/lists/*

RUN pip install pybind11

# C++ ソースのみコピー (Python 部分はランタイムステージでコピー)
COPY cpp_port ./cpp_port

# 拡張モジュールをコンパイル。
# .cc が `#include "open_spiel/games/koikoi/..."` 形式なので、
# 同名のディレクトリ構造を symlink で用意して -I で食わせる。
RUN mkdir -p build_inc/open_spiel/games \
 && ln -s /build/cpp_port/koikoi build_inc/open_spiel/games/koikoi \
 && PY_INC=$(python3 -c "import sysconfig; print(sysconfig.get_paths()['include'])") \
 && PB_INC=$(python3 -c "import pybind11; print(pybind11.get_include())") \
 && EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))") \
 && g++ -std=c++17 -O2 -Wall -shared -fPIC \
        -I"$PY_INC" -I"$PB_INC" -I /build/build_inc \
        cpp_port/koikoi/koikoi_engine.cc \
        cpp_port/koikoi/koikoi_yaku.cc \
        cpp_port/koikoi/koikoi_pybind.cc \
        -o "cpp_port/koikoi/_koikoi_native${EXT_SUFFIX}"


# =========================================
# 2. ランタイムステージ
# =========================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-serve.txt ./
RUN pip install -r requirements-serve.txt

# Python 部分。engine.py は koikoi_cpp 経由で C++ 拡張を呼ぶ薄い shim、
# engine_py.py は環境変数 KOIKOI_USE_PY=1 時のフォールバック実装。
COPY core.py engine.py engine_py.py koikoi_cpp.py web.py ./
COPY static ./static

# C++ 拡張 .so のみビルドステージから持ってくる
RUN mkdir -p cpp_port/koikoi
COPY --from=builder /build/cpp_port/koikoi/_koikoi_native*.so ./cpp_port/koikoi/

RUN mkdir -p /app/kifu /app/models

RUN useradd --create-home --uid 1000 app \
 && chown -R app:app /app
USER app

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request, sys; \
urllib.request.urlopen('http://127.0.0.1:8800/api/cards', timeout=2); sys.exit(0)" \
  || exit 1

CMD ["python3", "web.py"]
