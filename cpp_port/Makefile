# Koi-Koi C++ ポート - 開発用 Makefile
#
# Targets:
#   make yaku_dump   — 役判定の stdin/stdout ドライバ (Python クロス検証用)
#   make validate    — yaku_dump をビルド + Python と 10020 ケース比較
#   make clean       — ビルド成果物削除

OPEN_SPIEL_ROOT := $(abspath $(CURDIR)/../vendor/open_spiel)
KOIKOI_DIR := $(CURDIR)/koikoi

# OS 判定: Linux と Mac で linker フラグが違う
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
  CXX := clang++
  PY_LDFLAGS := -undefined dynamic_lookup
else
  CXX := g++
  PY_LDFLAGS :=
endif

CXXFLAGS := -std=c++17 -O2 -Wall -I$(OPEN_SPIEL_ROOT)

.PHONY: all validate validate_yaku validate_engine pybind clean setup

all: yaku_dump engine_dump pybind

# === pybind11 拡張モジュール ===
PY3 := /usr/bin/python3
PY_INC := /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/include/python3.9
PB_INC := $(OPEN_SPIEL_ROOT)/pybind11/include
PY_EXT := $(shell $(PY3) -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')
PYBIND_SO := $(KOIKOI_DIR)/_koikoi_native$(PY_EXT)

pybind: $(PYBIND_SO)

$(PYBIND_SO): $(KOIKOI_DIR)/koikoi_engine.cc $(KOIKOI_DIR)/koikoi_yaku.cc $(KOIKOI_DIR)/koikoi_pybind.cc $(KOIKOI_DIR)/koikoi_engine.h $(KOIKOI_DIR)/koikoi_yaku.h $(KOIKOI_DIR)/koikoi_cards.h
	$(CXX) -std=c++17 -O2 -Wall -shared -fPIC $(PY_LDFLAGS) \
	  -I"$(PY_INC)" -I"$(PB_INC)" -I"$(OPEN_SPIEL_ROOT)" \
	  $(KOIKOI_DIR)/koikoi_engine.cc \
	  $(KOIKOI_DIR)/koikoi_yaku.cc \
	  $(KOIKOI_DIR)/koikoi_pybind.cc \
	  -o $@

yaku_dump: $(KOIKOI_DIR)/yaku_dump
engine_dump: $(KOIKOI_DIR)/engine_dump

$(KOIKOI_DIR)/yaku_dump: $(KOIKOI_DIR)/koikoi_yaku.cc $(KOIKOI_DIR)/yaku_dump_main.cc $(KOIKOI_DIR)/koikoi_yaku.h $(KOIKOI_DIR)/koikoi_cards.h
	$(CXX) $(CXXFLAGS) \
	  $(KOIKOI_DIR)/koikoi_yaku.cc \
	  $(KOIKOI_DIR)/yaku_dump_main.cc \
	  -o $@

$(KOIKOI_DIR)/engine_dump: $(KOIKOI_DIR)/koikoi_engine.cc $(KOIKOI_DIR)/koikoi_yaku.cc $(KOIKOI_DIR)/engine_dump_main.cc $(KOIKOI_DIR)/koikoi_engine.h $(KOIKOI_DIR)/koikoi_yaku.h $(KOIKOI_DIR)/koikoi_cards.h
	$(CXX) $(CXXFLAGS) \
	  $(KOIKOI_DIR)/koikoi_engine.cc \
	  $(KOIKOI_DIR)/koikoi_yaku.cc \
	  $(KOIKOI_DIR)/engine_dump_main.cc \
	  -o $@

validate: validate_yaku validate_engine validate_pybind

validate_pybind: pybind
	cd .. && /usr/bin/python3 -c "from engine import KoikoiEngine, rule_based_policy; e = KoikoiEngine(); e.reset(seed=1); n=0; \
import sys; \
[e.step(rule_based_policy(e, e.current_player)) or n for n in range(500) if not e.done]; \
print('pybind smoke OK: winner=', e.winner, 'score=', e.win_score)"

validate_yaku: $(KOIKOI_DIR)/yaku_dump
	cd .. && python3 cpp_port/validate_yaku.py

validate_engine: $(KOIKOI_DIR)/engine_dump
	cd .. && python3 cpp_port/validate_engine.py

setup:
	@if [ ! -e $(OPEN_SPIEL_ROOT)/open_spiel/games/koikoi ]; then \
	  echo "Symlinking cpp_port/koikoi into vendor/open_spiel/open_spiel/games/"; \
	  ln -s $(KOIKOI_DIR) $(OPEN_SPIEL_ROOT)/open_spiel/games/koikoi; \
	fi

clean:
	rm -f $(KOIKOI_DIR)/yaku_dump $(KOIKOI_DIR)/engine_dump $(PYBIND_SO) $(KOIKOI_DIR)/*.o
