"use strict";

const PHASE_MSG = {
  HAND_PLAY: "手札からカードを選んでください",
  HAND_MATCH: "取るカードを選んでください",
  DRAW_MATCH: "取るカードを選んでください",
  KOIKOI: "",
  DONE: "",
};

let CARDS = [];
let state = null;
let prevState = null;
let kifuOpen = false;
let animating = false;

// ============ Init ============

document.addEventListener("DOMContentLoaded", async () => {
  CARDS = await api("GET", "/api/cards");

  $("btn-start").onclick = startGame;
  $("btn-menu").onclick = backToTitle;
  $("btn-settings").onclick = () => showScreen("settings-screen");
  $("btn-settings-back").onclick = backToTitle;
  $("btn-kifu-list").onclick = showKifuList;
  $("btn-kifu-back").onclick = backToTitle;
  $("btn-kifu-toggle").onclick = toggleKifu;
  $("btn-kifu-close").onclick = toggleKifu;
  $("btn-koikoi").onclick = () => doAction(48);
  $("btn-showdown").onclick = () => doAction(49);
  $("btn-next-round").onclick = nextRound;
  $("btn-save-kifu").onclick = saveKifu;
  $("btn-back-title").onclick = backToTitle;
});

// ============ API ============

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  return resp.json();
}

// ============ Navigation ============

function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.add("hidden"));
  $(id).classList.remove("hidden");
}

function backToTitle() {
  showScreen("start-screen");
}

// ============ Game Flow ============

function readRules() {
  return {
    koikoi_double: $("rule-koikoi-double").checked,
    seven_plus_double: $("rule-7plus-double").checked,
    hanami: $("rule-hanami").checked,
    tsukimi: $("rule-tsukimi").checked,
    exhaust: document.querySelector('input[name="rule-exhaust"]:checked').value.replace("-", "_"),
  };
}

async function startGame() {
  const rounds = parseInt($("round-select").value);
  const rules = readRules();
  prevState = null;
  state = await api("POST", "/api/new_game", { rounds, rules });
  showScreen("game-screen");
  $("opp-hand-cards").innerHTML = "";
  $("opp-action-log").classList.add("hidden");
  render();
}

async function doAction(action) {
  if (animating) return;
  prevState = state;
  state = await api("POST", "/api/action", { action });
  await renderWithOpponentAnimation();
}

async function nextRound() {
  hideModal("round-result-modal");
  prevState = null;
  $("opp-hand-cards").innerHTML = "";
  $("opp-action-log").classList.add("hidden");
  state = await api("POST", "/api/next_round");
  if (state.round_started === false) {
    showGameOver();
  } else {
    render();
  }
}

async function saveKifu() {
  const result = await api("POST", "/api/save_kifu");
  if (result.path) {
    alert("棋譜を保存しました:\n" + result.path);
  }
}

// ============ Render ============

function render() {
  if (!state) return;

  // Header info
  $("round-info").textContent = `${state.round}/${state.total_rounds}局`;
  $("score-info").textContent = `[あなた ${state.scores[0]} - ${state.scores[1]} 相手]`;
  $("deck-count").textContent = state.deck_remaining;
  $("deck-display").classList.toggle("hidden", state.deck_remaining === 0);

  // Phase message
  let msg = "";
  if (state.done) {
    if (state.winner === 0) msg = "あなたの勝ち!";
    else if (state.winner === 1) msg = "相手の勝ち";
    else msg = "引き分け";
  } else if (state.phase === "KOIKOI") {
    msg = "";
  } else {
    msg = PHASE_MSG[state.phase] || "";
  }
  $("phase-message").textContent = msg;

  renderHand();
  renderField();
  renderCaptured("player-captured", state.player_captured);
  renderCaptured("opponent-captured", state.opponent_captured);
  renderYakuInfo();
  renderOpponentHand();
  renderKifuContent();

  // Modals
  if (state.phase === "KOIKOI" && !state.done) {
    showKoikoiModal();
  } else {
    hideModal("koikoi-modal");
  }

  if (state.done) {
    if (state.game_over) {
      showGameOver();
    } else {
      showRoundResult();
    }
  }
}

function renderHand() {
  const container = $("hand-cards");
  const oldIds = new Set([...container.querySelectorAll(".card")].map(c => c.dataset.cardId));
  container.innerHTML = "";
  const legal = new Set(state.legal_actions);
  const isHandPhase = state.phase === "HAND_PLAY";
  const fieldMonths = new Set(state.field.map(id => CARDS[id].month));

  for (const id of state.hand) {
    const canPlay = isHandPhase && legal.has(id);
    const hasMatch = canPlay && fieldMonths.has(CARDS[id].month);
    const el = createCardEl(id, {
      selectable: hasMatch,
      playable: canPlay && !hasMatch,
      onClick: canPlay ? () => doAction(id) : null,
    });
    if (!oldIds.has(String(id))) el.classList.add("card-enter");
    if (canPlay) {
      el.addEventListener("mouseenter", () => highlightFieldMatches(id));
      el.addEventListener("mouseleave", clearFieldHighlight);
    }
    container.appendChild(el);
  }
}

function renderField() {
  const container = $("field-cards");
  const oldIds = new Set([...container.querySelectorAll(".card")].map(c => c.dataset.cardId));
  container.innerHTML = "";
  const legal = new Set(state.legal_actions);
  const isMatchPhase = state.phase === "HAND_MATCH" || state.phase === "DRAW_MATCH";

  if (state.pending_card !== null && state.pending_card !== undefined) {
    const el = createCardEl(state.pending_card, { pending: true });
    if (!oldIds.has(String(state.pending_card))) el.classList.add("card-enter");
    container.appendChild(el);
  }

  for (const id of state.field) {
    const selectable = isMatchPhase && legal.has(id);
    const el = createCardEl(id, { selectable, onClick: selectable ? () => doAction(id) : null });
    container.appendChild(el);
  }
}

function renderCaptured(containerId, cardIds) {
  const container = $(containerId);
  container.innerHTML = "";

  const groups = { "光": [], "種": [], "短冊": [], "カス": [] };
  for (const id of cardIds) {
    const t = CARDS[id].card_type;
    (groups[t] || groups["カス"]).push(id);
  }

  const labels = { "光": "光", "種": "タネ", "短冊": "タン", "カス": "カス" };
  for (const [type, ids] of Object.entries(groups)) {
    const section = document.createElement("div");
    section.className = "cap-section";

    const label = document.createElement("div");
    label.className = "cap-label";
    label.textContent = `${labels[type]} ${ids.length}`;
    section.appendChild(label);

    const row = document.createElement("div");
    row.className = "cap-row";
    ids.sort((a, b) => CARDS[a].month - CARDS[b].month);
    for (const id of ids) {
      row.appendChild(createCardEl(id, { small: true }));
    }
    section.appendChild(row);
    container.appendChild(section);
  }
}

function renderYakuInfo() {
  $("player-yaku-info").textContent = formatYaku(state.player_yaku);
  $("opp-yaku-info").textContent = formatYaku(state.opponent_yaku);
}

function formatYaku(yakuList) {
  if (!yakuList || yakuList.length === 0) return "";
  return yakuList.map(([name, pts]) => `${name}(${pts}点)`).join(" ");
}

function renderOpponentHand() {
  const container = $("opp-hand-cards");
  const n = state.opponent_hand_count;
  const current = container.children.length;

  if (current > n) {
    for (let i = current - 1; i >= n; i--) {
      const card = container.children[i];
      if (card) {
        card.classList.add("card-exit");
        setTimeout(() => card.remove(), 450);
      }
    }
  } else {
    for (let i = current; i < n; i++) {
      const el = createCardBackEl();
      el.classList.add("card-enter");
      container.appendChild(el);
    }
  }
}

function createCardBackEl() {
  const el = document.createElement("div");
  el.className = "card card-back-img";
  const img = document.createElement("img");
  img.src = "/cards/back.svg";
  img.alt = "裏";
  img.draggable = false;
  el.appendChild(img);
  return el;
}

// ============ Opponent Animation ============

async function renderWithOpponentAnimation() {
  const actions = state.opponent_actions || [];
  if (actions.length === 0) {
    render();
    return;
  }

  animating = true;
  render();

  const log = $("opp-action-log");
  await sleep(400);

  for (let i = 0; i < actions.length; i++) {
    const act = actions[i];
    const label = formatOpponentAction(act);
    log.textContent = label;
    log.classList.remove("hidden");
    log.classList.remove("log-fade");
    void log.offsetWidth;
    log.classList.add("log-fade");
    await sleep(1800);
    if (i < actions.length - 1) await sleep(300);
  }

  await sleep(400);
  log.classList.add("hidden");
  animating = false;
}

function formatOpponentAction(act) {
  if (act.phase === "HAND_PLAY") return `相手: ${act.card_name} を出した`;
  if (act.phase === "HAND_MATCH") return `相手: ${act.card_name} を取った`;
  if (act.phase === "DRAW_MATCH") return `相手: 山札から ${act.card_name} を取った`;
  if (act.card_name === "こいこい") return "相手: こいこい!";
  if (act.card_name === "勝負") return "相手: 勝負!";
  return `相手: ${act.card_name || act.action}`;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ============ Field Highlight ============

function highlightFieldMatches(handCardId) {
  const month = CARDS[handCardId].month;
  const fieldCards = $("field-cards").querySelectorAll(".card");
  let hasMatch = false;
  for (const el of fieldCards) {
    const cid = Number(el.dataset.cardId);
    if (CARDS[cid].month === month) {
      el.classList.add("highlight-match");
      hasMatch = true;
    } else {
      el.classList.add("dimmed");
    }
  }
  if (!hasMatch) {
    for (const el of fieldCards) el.classList.remove("dimmed");
  }
}

function clearFieldHighlight() {
  const fieldCards = $("field-cards").querySelectorAll(".card");
  for (const el of fieldCards) {
    el.classList.remove("dimmed", "highlight-match");
  }
}

// ============ Card Element ============

function createCardEl(cardId, opts = {}) {
  const card = CARDS[cardId];
  const el = document.createElement("div");

  let cls = "card";
  if (opts.selectable) cls += " selectable";
  if (opts.playable) cls += " playable";
  if (opts.selected) cls += " selected";
  if (opts.pending) cls += " pending";

  el.className = cls;
  el.dataset.cardId = cardId;

  const img = document.createElement("img");
  img.src = `/cards/${cardId}.svg`;
  img.alt = card.name;
  img.draggable = false;
  el.appendChild(img);

  if (opts.onClick) el.addEventListener("click", opts.onClick);
  return el;
}

// ============ Modals ============

function showKoikoiModal() {
  const yakuHtml = state.player_yaku.map(([name, pts]) =>
    `<span class="yaku-name">${name}</span><span class="yaku-pts">${pts}点</span>`
  ).join("<br>");
  $("koikoi-yaku").innerHTML = yakuHtml +
    `<br><span style="color:var(--text-dim)">合計: ${state.player_yaku_points}点</span>`;
  showModal("koikoi-modal");
}

function showRoundResult() {
  const w = state.winner;
  const title = w === 0 ? "あなたの勝ち!" : w === 1 ? "相手の勝ち" : "引き分け";
  const yaku = w === 0 ? state.player_yaku : state.opponent_yaku;
  const yakuStr = yaku.length > 0
    ? yaku.map(([n, p]) => `${n} (${p}点)`).join("、")
    : "なし";

  $("result-title").textContent = `${state.round}局目 - ${title}`;
  $("result-detail").innerHTML =
    `得点: ${state.win_score}点<br>` +
    `役: ${yakuStr}<br><br>` +
    `<strong>あなた ${state.scores[0]} - ${state.scores[1]} 相手</strong>`;

  if (state.game_over) {
    $("btn-next-round").textContent = "最終結果へ";
  } else {
    $("btn-next-round").textContent = "次の局へ";
  }
  showModal("round-result-modal");
}

function showGameOver() {
  hideModal("round-result-modal");
  const s0 = state.scores[0], s1 = state.scores[1];
  let title;
  if (s0 > s1) title = "勝利!";
  else if (s0 < s1) title = "敗北...";
  else title = "引き分け";

  $("gameover-title").textContent = title;
  $("gameover-detail").innerHTML =
    `最終スコア<br>` +
    `<strong style="font-size:1.4rem">あなた ${s0} - ${s1} 相手</strong><br><br>` +
    `全${state.total_rounds}局`;
  showModal("game-over-modal");
}

function showModal(id) { $(id).classList.remove("hidden"); }
function hideModal(id) { $(id).classList.add("hidden"); }

// ============ Kifu ============

function toggleKifu() {
  kifuOpen = !kifuOpen;
  $("kifu-panel").classList.toggle("hidden", !kifuOpen);
  if (kifuOpen) renderKifuContent();
}

async function renderKifuContent() {
  if (!kifuOpen) return;
  const data = await api("GET", "/api/kifu");
  const container = $("kifu-content");
  container.innerHTML = "";

  if (!data.rounds) return;

  for (const round of data.rounds) {
    const header = document.createElement("div");
    header.className = "kifu-round-header";
    let result = "";
    if (round.winner !== null && round.winner !== undefined) {
      result = round.winner === 0 ? ` → あなた +${round.score}` : ` → 相手 +${round.score}`;
    }
    header.textContent = `第${round.round}局 (親: ${round.oya === 0 ? "あなた" : "相手"})${result}`;
    container.appendChild(header);

    if (round.special) {
      const sp = document.createElement("div");
      sp.className = "kifu-entry";
      sp.textContent = `特殊: ${round.special}`;
      container.appendChild(sp);
    }

    for (const act of (round.actions || [])) {
      const entry = document.createElement("div");
      entry.className = `kifu-entry player-${act.player}`;
      const who = act.player === 0 ? "あなた" : "相手";
      const phase = act.phase.replace("HAND_", "手:").replace("DRAW_", "引:").replace("KOIKOI", "判断");
      entry.textContent = `${who} [${phase}] ${act.card_name || act.action}`;
      container.appendChild(entry);
    }
  }
  container.scrollTop = container.scrollHeight;
}

async function showKifuList() {
  showScreen("kifu-list-screen");
  const files = await api("GET", "/api/kifu_list");
  const container = $("kifu-list");
  container.innerHTML = "";

  if (files.length === 0) {
    container.innerHTML = '<div style="color:var(--text-dim)">保存された棋譜はありません</div>';
    return;
  }

  for (const name of files) {
    const item = document.createElement("div");
    item.className = "kifu-list-item";
    const display = name.replace("kifu_", "").replace(".json", "").replace(/_/g, " ");
    item.textContent = display;
    item.onclick = () => loadKifuDetail(name);
    container.appendChild(item);
  }
}

async function loadKifuDetail(name) {
  const data = await api("GET", `/api/kifu_load/${name}`);
  let html = `<h3 style="color:var(--gold);margin-bottom:12px">${name}</h3>`;
  html += `<div>スコア: ${data.scores[0]} - ${data.scores[1]}</div>`;
  html += `<div>勝者: ${data.winner === 0 ? "あなた" : data.winner === 1 ? "相手" : "引分"}</div>`;
  html += `<hr style="border-color:#333;margin:12px 0">`;

  for (const round of data.rounds) {
    html += `<div class="kifu-round-header">第${round.round}局</div>`;
    for (const act of (round.actions || [])) {
      const who = act.player === 0 ? "あなた" : "相手";
      html += `<div class="kifu-entry player-${act.player}">${who}: ${act.card_name || act.action}</div>`;
    }
    if (round.winner !== null && round.winner !== undefined) {
      const w = round.winner === 0 ? "あなた" : "相手";
      html += `<div style="color:var(--gold)">→ ${w} +${round.score}点</div>`;
    }
  }

  $("kifu-list").innerHTML = html;
}

// ============ Util ============

function $(id) { return document.getElementById(id); }
