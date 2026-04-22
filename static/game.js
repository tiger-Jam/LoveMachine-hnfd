"use strict";

// ================================================================
// Phase / timings
// ================================================================

const PHASE_MSG = {
  HAND_PLAY: "手札からカードを選んでください",
  HAND_MATCH: "取るカードを選んでください",
  DRAW_MATCH: "取るカードを選んでください",
  KOIKOI: "",
  DONE: "",
};

const T = {
  deal_stagger: 55,
  deal_fly: 280,
  fly: 360,
  flip: 420,
  pause_meet: 220,
  pause_after: 240,
  banner_hold: 900,
  yaku_hold: 1400,
  opp_pre: 380,
};

// ================================================================
// Globals
// ================================================================

let CARDS = [];
let state = null;         // last server state (the authoritative target)
let animating = false;
let kifuOpen = false;
let pendingCardId = null; // card currently sitting on the field awaiting match choice
let visibleDeckCount = 0;

const cardEls = {};       // id -> HTMLElement
const oppHandBacks = [];  // queue of face-down opp hand placeholder elements

// ================================================================
// Init
// ================================================================

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

async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  return resp.json();
}

function showScreen(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.add("hidden"));
  $(id).classList.remove("hidden");
}

function backToTitle() {
  animating = false;
  hideAllModals();
  clearBoard();
  showScreen("start-screen");
}

function hideAllModals() {
  hideModal("koikoi-modal");
  hideModal("round-result-modal");
  hideModal("game-over-modal");
}

// ================================================================
// Game flow
// ================================================================

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
  clearBoard();
  state = await api("POST", "/api/new_game", { rounds, rules });
  showScreen("game-screen");
  ensureCapturedStructure("player-captured");
  ensureCapturedStructure("opponent-captured");
  await beginRound();
}

async function nextRound() {
  hideModal("round-result-modal");
  clearBoard();
  state = await api("POST", "/api/next_round");
  if (state.round_started === false) {
    showGameOver();
    return;
  }
  await beginRound();
}

async function beginRound() {
  animating = true;
  renderHeader();
  hideModal("koikoi-modal");
  hideModal("round-result-modal");
  hideModal("game-over-modal");
  await animateInitialDeal(state.deal_snapshot);

  // Any opening opponent moves (opponent as oya)
  if (state.transitions && state.transitions.length > 0) {
    await runTransitions(state.transitions);
  }

  animating = false;
  await finalizeFromState(state);
}

async function doAction(action) {
  if (animating) return;
  animating = true;
  clearFieldHighlight();
  applyInteractivity(null); // disable clicks while animating
  hideModal("koikoi-modal");

  const resp = await api("POST", "/api/action", { action });
  state = resp;

  if (state.transitions && state.transitions.length > 0) {
    await runTransitions(state.transitions);
  }

  animating = false;
  await finalizeFromState(state);
}

async function saveKifu() {
  const result = await api("POST", "/api/save_kifu");
  if (result.path) {
    alert("棋譜を保存しました:\n" + result.path);
  }
}

// ================================================================
// DOM registry
// ================================================================

function makeCardEl(id) {
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.cardId = id;

  const inner = document.createElement("div");
  inner.className = "card-inner";

  const front = document.createElement("div");
  front.className = "card-face card-front";
  const fimg = document.createElement("img");
  fimg.src = `/cards/${id}.svg`;
  fimg.alt = CARDS[id].name;
  fimg.draggable = false;
  front.appendChild(fimg);

  const back = document.createElement("div");
  back.className = "card-face card-back";
  const bimg = document.createElement("img");
  bimg.src = "/cards/back.svg";
  bimg.alt = "裏";
  bimg.draggable = false;
  back.appendChild(bimg);

  inner.appendChild(front);
  inner.appendChild(back);
  el.appendChild(inner);
  return el;
}

function cardEl(id) {
  if (!cardEls[id]) cardEls[id] = makeCardEl(id);
  return cardEls[id];
}

function makeOppBackEl() {
  const el = document.createElement("div");
  el.className = "card opp-back";
  const img = document.createElement("img");
  img.src = "/cards/back.svg";
  img.alt = "裏";
  img.draggable = false;
  img.className = "card-plain-img";
  el.appendChild(img);
  return el;
}

// ================================================================
// Zone helpers
// ================================================================

const CAP_TYPES = ["光", "種", "短冊", "カス"];
const CAP_LABELS = { "光": "光", "種": "タネ", "短冊": "タン", "カス": "カス" };

function ensureCapturedStructure(containerId) {
  const container = $(containerId);
  if (container.dataset.inited === "1") return;
  container.dataset.inited = "1";
  container.innerHTML = "";
  for (const t of CAP_TYPES) {
    const section = document.createElement("div");
    section.className = "cap-section";
    section.dataset.capType = t;

    const label = document.createElement("div");
    label.className = "cap-label";
    label.textContent = `${CAP_LABELS[t]} 0`;

    const row = document.createElement("div");
    row.className = "cap-row";

    section.appendChild(label);
    section.appendChild(row);
    container.appendChild(section);
  }
}

function capRow(containerId, type) {
  return $(containerId).querySelector(`.cap-section[data-cap-type="${type}"] .cap-row`);
}

function updateCapLabels(containerId) {
  const container = $(containerId);
  for (const section of container.children) {
    const t = section.dataset.capType;
    const row = section.querySelector(".cap-row");
    section.querySelector(".cap-label").textContent = `${CAP_LABELS[t]} ${row.children.length}`;
  }
}

function capInsertRef(containerId, id) {
  const type = CARDS[id].card_type;
  const row = capRow(containerId, type);
  const month = CARDS[id].month;
  for (const child of row.children) {
    const cid = Number(child.dataset.cardId);
    if (CARDS[cid].month > month) return { row, ref: child };
    if (CARDS[cid].month === month && cid > id) return { row, ref: child };
  }
  return { row, ref: null };
}

function fieldInsertRef(id) {
  const row = $("field-cards");
  const month = CARDS[id].month;
  for (const child of row.children) {
    const cid = Number(child.dataset.cardId);
    if (CARDS[cid].month > month) return { row, ref: child };
    if (CARDS[cid].month === month && cid > id) return { row, ref: child };
  }
  return { row, ref: null };
}

function handInsertRef(id) {
  const row = $("hand-cards");
  for (const child of row.children) {
    const cid = Number(child.dataset.cardId);
    if (cid > id) return { row, ref: child };
  }
  return { row, ref: null };
}

// ================================================================
// Overlay / FLIP
// ================================================================

function overlay() { return $("anim-overlay"); }

function placeAtOverlay(el, rect) {
  overlay().appendChild(el);
  el.style.position = "absolute";
  el.style.left = rect.left + "px";
  el.style.top = rect.top + "px";
  el.style.width = rect.width + "px";
  el.style.height = rect.height + "px";
  el.style.margin = "0";
  el.style.transform = "";
  el.style.transition = "";
}

function clearOverlayStyles(el) {
  el.style.position = "";
  el.style.left = "";
  el.style.top = "";
  el.style.width = "";
  el.style.height = "";
  el.style.margin = "";
  el.style.transform = "";
  el.style.transition = "";
  el.style.transformOrigin = "";
  el.style.zIndex = "";
}

async function flipTo(el, place, opts = {}) {
  const duration = opts.duration ?? T.fly;
  const easing = opts.easing ?? "cubic-bezier(.22,1,.36,1)";
  const fromRect = el.getBoundingClientRect();

  clearOverlayStyles(el);
  place(el);

  const toRect = el.getBoundingClientRect();
  const dx = fromRect.left - toRect.left;
  const dy = fromRect.top - toRect.top;
  const sw = toRect.width === 0 ? 1 : fromRect.width / toRect.width;
  const sh = toRect.height === 0 ? 1 : fromRect.height / toRect.height;

  el.style.transformOrigin = "top left";
  el.style.transition = "none";
  el.style.transform = `translate(${dx}px, ${dy}px) scale(${sw}, ${sh})`;
  void el.offsetWidth;
  el.style.transition = `transform ${duration}ms ${easing}`;
  el.style.transform = "";

  await sleep(duration);
  el.style.transition = "";
  el.style.transformOrigin = "";
}

async function flyToPoint(el, rect, opts = {}) {
  // el must already be in overlay (absolute-positioned)
  const duration = opts.duration ?? T.fly;
  const easing = opts.easing ?? "cubic-bezier(.22,1,.36,1)";

  const curRect = el.getBoundingClientRect();

  el.style.transition = "none";
  el.style.left = rect.left + "px";
  el.style.top = rect.top + "px";
  el.style.width = rect.width + "px";
  el.style.height = rect.height + "px";

  const newRect = el.getBoundingClientRect();
  const dx = curRect.left - newRect.left;
  const dy = curRect.top - newRect.top;
  const sw = newRect.width === 0 ? 1 : curRect.width / newRect.width;
  const sh = newRect.height === 0 ? 1 : curRect.height / newRect.height;

  el.style.transformOrigin = "top left";
  el.style.transform = `translate(${dx}px, ${dy}px) scale(${sw}, ${sh})`;
  void el.offsetWidth;
  el.style.transition = `transform ${duration}ms ${easing}`;
  el.style.transform = "";

  await sleep(duration);
  el.style.transition = "";
  el.style.transformOrigin = "";
}

// ================================================================
// Initial deal
// ================================================================

function clearBoard() {
  pendingCardId = null;
  oppHandBacks.length = 0;
  for (const id in cardEls) delete cardEls[id];
  const zones = ["hand-cards", "field-cards", "opp-hand-cards"];
  for (const z of zones) { const el = $(z); if (el) el.innerHTML = ""; }
  // Reset captured zones
  for (const cid of ["player-captured", "opponent-captured"]) {
    const el = $(cid);
    if (el) {
      el.innerHTML = "";
      delete el.dataset.inited;
    }
  }
  overlay().innerHTML = "";
  hideBanner();
  hideYakuBanner();
}

async function animateInitialDeal(snap) {
  ensureCapturedStructure("player-captured");
  ensureCapturedStructure("opponent-captured");

  const deckEl = $("deck-display");
  deckEl.classList.remove("hidden");

  // Pre-place every dealt card in its final position as invisible,
  // so the layout is stable and FLIP-from-deck works without shifts.
  const handIds = [...snap.hand].sort((a, b) => CARDS[a].month - CARDS[b].month || a - b);
  const fieldIds = [...snap.field].sort((a, b) => CARDS[a].month - CARDS[b].month || a - b);
  const oppCount = snap.opponent_hand_count;

  const handContainer = $("hand-cards");
  const fieldContainer = $("field-cards");
  const oppContainer = $("opp-hand-cards");

  for (const id of handIds) {
    const el = cardEl(id);
    el.style.visibility = "hidden";
    handContainer.appendChild(el);
  }
  for (const id of fieldIds) {
    const el = cardEl(id);
    el.style.visibility = "hidden";
    fieldContainer.appendChild(el);
  }
  const oppEls = [];
  for (let i = 0; i < oppCount; i++) {
    const el = makeOppBackEl();
    el.style.visibility = "hidden";
    oppContainer.appendChild(el);
    oppEls.push(el);
    oppHandBacks.push(el);
  }

  // Let layout settle
  await new Promise(r => requestAnimationFrame(() => r()));

  const deckRect = deckEl.getBoundingClientRect();

  const totalToDeal = oppCount + fieldIds.length + handIds.length;
  const startCount = snap.deck_remaining + totalToDeal;
  renderDeckCount(startCount);

  // Traditional deal: 4 to opponent, 4 to field, 4 to you — repeat.
  const order = [];
  const chunks = [[0, 4], [4, 8]];
  for (const [s, e] of chunks) {
    for (let i = s; i < e && i < oppEls.length; i++) order.push(oppEls[i]);
    for (let i = s; i < e && i < fieldIds.length; i++) order.push(cardEl(fieldIds[i]));
    for (let i = s; i < e && i < handIds.length; i++) order.push(cardEl(handIds[i]));
  }

  let dealtCount = 0;
  const animations = order.map((el, i) => (async () => {
    await sleep(i * T.deal_stagger);
    dealtCount++;
    renderDeckCount(startCount - dealtCount);
    await flyFromDeckTo(el, deckRect, T.deal_fly);
  })());
  await Promise.all(animations);
  renderDeckCount(snap.deck_remaining);
}

async function flyFromDeckTo(el, deckRect, duration) {
  const toRect = el.getBoundingClientRect();
  el.style.visibility = "visible";
  const dx = deckRect.left - toRect.left;
  const dy = deckRect.top - toRect.top;
  const sw = toRect.width === 0 ? 1 : deckRect.width / toRect.width;
  const sh = toRect.height === 0 ? 1 : deckRect.height / toRect.height;

  el.style.transformOrigin = "top left";
  el.style.transition = "none";
  el.style.transform = `translate(${dx}px, ${dy}px) scale(${sw}, ${sh})`;
  void el.offsetWidth;
  el.style.transition = `transform ${duration}ms cubic-bezier(.22,1,.36,1)`;
  el.style.transform = "";

  await sleep(duration);
  el.style.transition = "";
  el.style.transformOrigin = "";
}

// ================================================================
// Transition runner
// ================================================================

async function runTransitions(transitions) {
  for (const tr of transitions) {
    await runOneTransition(tr);
  }
}

async function runOneTransition(tr) {
  const actor = tr.actor;
  const events = [...tr.events];

  // If this transition is a match resolution, prepend a synthetic event
  if (tr.phase_before === "HAND_MATCH" || tr.phase_before === "DRAW_MATCH") {
    events.unshift({ type: "resolve_match", actor, chosen: tr.action });
  }

  for (const ev of events) {
    await animateEvent(actor, ev);
  }

  // Keep displayed snapshot rough-synced (no-op; we rebuild from DOM)
}

async function animateEvent(actor, ev) {
  switch (ev.type) {
    case "hand_no_match":
      await ev_handNoMatch(actor, ev.card);
      break;
    case "hand_match":
      await ev_handMatch(actor, ev.card, [ev.matched]);
      break;
    case "hand_match_all":
      await ev_handMatch(actor, ev.card, ev.matched);
      break;
    case "hand_choose":
      await ev_handChoose(actor, ev.card);
      break;
    case "draw":
      await ev_draw(ev.card);
      break;
    case "draw_match":
      await ev_drawMatch(actor, ev.card, [ev.matched]);
      break;
    case "draw_match_all":
      await ev_drawMatch(actor, ev.card, ev.matched);
      break;
    case "draw_choose":
      await ev_drawChoose(actor, ev.card);
      break;
    case "resolve_match":
      await ev_resolveMatch(actor, ev.chosen);
      break;
    case "yaku_formed":
      await ev_yakuFormed(ev.player, ev.yaku, ev.points);
      break;
    case "koikoi":
      await ev_call(ev.player, "こいこい!");
      break;
    case "showdown":
      await ev_call(ev.player, "勝負!");
      break;
    case "round_end":
      // The modal pops via finalizeFromState — nothing extra here.
      await sleep(250);
      break;
    case "exhausted":
      await ev_call(null, "流局");
      break;
    case "bonus_7plus":
    case "bonus_opponent_koikoi":
      // Minor; no dedicated animation
      break;
  }
}

// ---------- Event animations ----------

async function ev_handNoMatch(actor, cardId) {
  if (actor === 0) {
    await sleep(120);
    await flipTo(cardEl(cardId), el => {
      const { row, ref } = fieldInsertRef(cardId);
      row.insertBefore(el, ref);
    }, { duration: T.fly });
  } else {
    const el = await revealFromOppHand(cardId);
    await flipTo(el, e => {
      const { row, ref } = fieldInsertRef(cardId);
      row.insertBefore(e, ref);
    }, { duration: T.fly });
  }
  await sleep(T.pause_after);
}

async function ev_handChoose(actor, cardId) {
  // Card goes to field as a pending/highlighted card
  if (actor === 0) {
    await sleep(120);
    await flipTo(cardEl(cardId), el => {
      const { row, ref } = fieldInsertRef(cardId);
      row.insertBefore(el, ref);
    });
  } else {
    const el = await revealFromOppHand(cardId);
    await flipTo(el, e => {
      const { row, ref } = fieldInsertRef(cardId);
      row.insertBefore(e, ref);
    });
  }
  cardEl(cardId).classList.add("pending");
  pendingCardId = cardId;
  await sleep(T.pause_after);
}

async function ev_handMatch(actor, cardId, matchedIds) {
  if (actor === 0) {
    await sleep(100);
  } else {
    await revealFromOppHand(cardId); // played card now in overlay
  }
  await captureSequence(actor, cardId, matchedIds);
}

async function ev_draw(cardId) {
  // Card comes off the deck, flips over, lands on field (no match).
  await sleep(120);
  await deckDrawReveal(cardId);
  await flipTo(cardEl(cardId), el => {
    const { row, ref } = fieldInsertRef(cardId);
    row.insertBefore(el, ref);
  }, { duration: T.fly });
  const drawnEl = cardEl(cardId);
  drawnEl.classList.add("just-drawn");
  await sleep(T.pause_after);
  drawnEl.classList.remove("just-drawn");
}

async function ev_drawMatch(actor, cardId, matchedIds) {
  await sleep(120);
  await deckDrawReveal(cardId);
  await captureSequence(actor, cardId, matchedIds);
}

async function ev_drawChoose(actor, cardId) {
  await sleep(120);
  await deckDrawReveal(cardId);
  await flipTo(cardEl(cardId), el => {
    const { row, ref } = fieldInsertRef(cardId);
    row.insertBefore(el, ref);
  }, { duration: T.fly });
  cardEl(cardId).classList.add("pending");
  pendingCardId = cardId;
  await sleep(T.pause_after);
}

async function ev_resolveMatch(actor, chosenId) {
  // pendingCardId (on field) + chosenId (on field) → actor's captured
  const pending = pendingCardId;
  pendingCardId = null;
  if (pending == null) return;
  cardEl(pending).classList.remove("pending");
  await captureSequence(actor, pending, [chosenId]);
}

// Shared: played card + matched list all fly to captured zone.
// `cardEl(cardId)` must already be detached to overlay OR currently in hand/field.
async function captureSequence(actor, cardId, matchedIds) {
  const capId = actor === 0 ? "player-captured" : "opponent-captured";
  const played = cardEl(cardId);
  const matched = matchedIds.map(id => cardEl(id));

  // Detach played to the overlay first so field/hand re-layouts
  // settle BEFORE we capture the matched cards' rects.
  if (played.parentElement !== overlay()) {
    const pr = played.getBoundingClientRect();
    placeAtOverlay(played, pr);
  }
  played.style.zIndex = "520";

  // Now read the first matched card's rect (post-relayout)
  const firstRect = matched[0].getBoundingClientRect();
  await flyToPoint(played, {
    left: firstRect.left,
    top: firstRect.top - 6,
    width: firstRect.width,
    height: firstRect.height,
  }, { duration: T.fly - 60 });

  // Step 2: pulse both played and matched cards
  played.classList.add("capture-glow");
  for (const m of matched) m.classList.add("capture-glow");
  await sleep(T.pause_meet);
  played.classList.remove("capture-glow");
  for (const m of matched) m.classList.remove("capture-glow");

  // Step 3: fly all cards into captured zone. Trigger in parallel with tiny stagger.
  const flights = [];
  const all = [...matched, played];
  for (let i = 0; i < all.length; i++) {
    const el = all[i];
    const id = Number(el.dataset.cardId);
    flights.push((async () => {
      await sleep(i * 50);
      await flipTo(el, e => {
        const { row, ref } = capInsertRef(capId, id);
        row.insertBefore(e, ref);
      }, { duration: T.fly });
      updateCapLabels(capId);
    })());
  }
  await Promise.all(flights);
  played.style.zIndex = "";
  await sleep(T.pause_after);
}

// ---------- Primitives ----------

async function revealFromOppHand(cardId) {
  const back = oppHandBacks.pop();
  let rect;
  if (back) {
    rect = back.getBoundingClientRect();
    back.remove();
  } else {
    // Fallback — center of opp hand row
    const row = $("opp-hand-cards").getBoundingClientRect();
    rect = { left: row.left + row.width / 2 - 21, top: row.top + 10, width: 42, height: 60 };
  }
  const el = cardEl(cardId);
  el.classList.remove("playable", "selectable", "pending");
  el.classList.add("flipped");
  placeAtOverlay(el, rect);
  el.style.zIndex = "510";

  // Lift slightly
  await sleep(T.opp_pre);
  el.classList.add("flipping");
  el.classList.remove("flipped");
  await sleep(T.flip);
  el.classList.remove("flipping");
  return el;
}

async function deckDrawReveal(cardId) {
  const deckEl = $("deck-display");
  if (!deckEl) return;
  const deckRect = deckEl.getBoundingClientRect();

  const el = cardEl(cardId);
  el.classList.remove("playable", "selectable", "pending");
  el.classList.add("flipped");
  placeAtOverlay(el, deckRect);
  el.style.zIndex = "510";

  // Roll the top of the stack down by one
  renderDeckCount(Math.max(0, visibleDeckCount - 1));

  // A small upward lift then flip
  const liftRect = {
    left: deckRect.left,
    top: deckRect.top - 18,
    width: deckRect.width,
    height: deckRect.height,
  };
  await flyToPoint(el, liftRect, { duration: 220 });
  el.classList.add("flipping");
  el.classList.remove("flipped");
  await sleep(T.flip);
  el.classList.remove("flipping");
}

// ---------- Yaku / Call banners ----------

async function ev_yakuFormed(player, yaku, points) {
  // Glow the captured cards that contribute to the yaku
  const capId = player === 0 ? "player-captured" : "opponent-captured";
  const contributing = findYakuContributors(player, yaku);

  for (const id of contributing) {
    const el = cardEls[id];
    if (el) el.classList.add("yaku-glow");
  }

  await showYakuBanner(player, yaku, points);

  for (const id of contributing) {
    const el = cardEls[id];
    if (el) el.classList.remove("yaku-glow");
  }
}

function findYakuContributors(player, yakuList) {
  const snap = player === 0 ? currentPlayerCap() : currentOppCap();
  const set = new Set();
  const byType = { "光": [], "種": [], "短冊": [], "カス": [] };
  const byName = {};
  for (const id of snap) {
    const c = CARDS[id];
    byType[c.card_type].push(id);
    byName[c.name] = id;
  }
  for (const [name /*, pts*/] of yakuList) {
    if (name === "五光" || name === "四光" || name === "雨四光" || name === "三光") {
      for (const id of byType["光"]) set.add(id);
    } else if (name === "赤短") {
      for (const id of byType["短冊"]) if (CARDS[id].tanzaku_type === "赤短") set.add(id);
    } else if (name === "青短") {
      for (const id of byType["短冊"]) if (CARDS[id].tanzaku_type === "青短") set.add(id);
    } else if (name === "たん") {
      for (const id of byType["短冊"]) set.add(id);
    } else if (name === "猪鹿蝶") {
      for (const n of ["萩に猪", "紅葉に鹿", "牡丹に蝶"]) if (byName[n] != null) set.add(byName[n]);
    } else if (name === "たね") {
      for (const id of byType["種"]) set.add(id);
    } else if (name === "カス") {
      for (const id of byType["カス"]) set.add(id);
    } else if (name === "花見で一杯") {
      for (const n of ["桜に幕", "菊に盃"]) if (byName[n] != null) set.add(byName[n]);
    } else if (name === "月見で一杯") {
      for (const n of ["芒に月", "菊に盃"]) if (byName[n] != null) set.add(byName[n]);
    }
  }
  return [...set];
}

function currentPlayerCap() {
  const row = $("player-captured");
  return [...row.querySelectorAll(".card")].map(e => Number(e.dataset.cardId));
}
function currentOppCap() {
  const row = $("opponent-captured");
  return [...row.querySelectorAll(".card")].map(e => Number(e.dataset.cardId));
}

async function showYakuBanner(player, yaku, points) {
  const banner = $("yaku-banner");
  const who = player === 0 ? "あなた" : "相手";
  const yakuLines = yaku.map(y => `<span class="yaku-line"><span class="yaku-name">${y[0]}</span><span class="yaku-pts">${y[1]}点</span></span>`).join("");
  banner.innerHTML = `
    <div class="yaku-banner-inner">
      <div class="yaku-heading">役!</div>
      <div class="yaku-who">${who}</div>
      <div class="yaku-list">${yakuLines}</div>
      <div class="yaku-total">合計 ${points} 点</div>
    </div>
  `;
  banner.classList.remove("hidden");
  banner.classList.remove("banner-out");
  void banner.offsetWidth;
  banner.classList.add("banner-in");
  await sleep(T.yaku_hold);
  banner.classList.remove("banner-in");
  banner.classList.add("banner-out");
  await sleep(300);
  banner.classList.add("hidden");
}

function hideYakuBanner() {
  const banner = $("yaku-banner");
  if (banner) {
    banner.classList.add("hidden");
    banner.classList.remove("banner-in", "banner-out");
    banner.innerHTML = "";
  }
}

async function ev_call(player, text) {
  const banner = $("call-banner");
  const cls = player === 0 ? "call-me" : player === 1 ? "call-opp" : "call-neutral";
  banner.innerHTML = `<div class="call-inner ${cls}">${text}</div>`;
  banner.classList.remove("hidden", "banner-out");
  void banner.offsetWidth;
  banner.classList.add("banner-in");
  await sleep(T.banner_hold);
  banner.classList.remove("banner-in");
  banner.classList.add("banner-out");
  await sleep(280);
  banner.classList.add("hidden");
}

function hideBanner() {
  const banner = $("call-banner");
  if (banner) {
    banner.classList.add("hidden");
    banner.classList.remove("banner-in", "banner-out");
    banner.innerHTML = "";
  }
}

// ================================================================
// Finalize / reconcile from authoritative state
// ================================================================

async function finalizeFromState(st) {
  renderHeader();
  renderPhaseMessage();
  reconcileField(st);
  reconcileHand(st);
  reconcileOppHand(st);
  reconcileCaptured(st);
  renderDeckCount(st.deck_remaining);
  renderYakuInfo();
  renderKifuContent();
  applyInteractivity(st);

  // Modals
  if (!st.done && st.phase === "KOIKOI") {
    showKoikoiModal();
  } else {
    hideModal("koikoi-modal");
  }

  if (st.done) {
    if (st.game_over) {
      await sleep(700);
      showGameOver();
    } else {
      await sleep(700);
      showRoundResult();
    }
  }
}

function reorderContainer(container, targetIds) {
  const targetSet = new Set(targetIds);
  for (const c of [...container.children]) {
    const cid = Number(c.dataset.cardId);
    if (Number.isNaN(cid)) continue;
    if (!targetSet.has(cid)) c.remove();
  }
  for (const id of targetIds) {
    container.appendChild(cardEl(id));
  }
}

function reconcileField(st) {
  const target = [...st.field].sort((a, b) => {
    if (CARDS[a].month !== CARDS[b].month) return CARDS[a].month - CARDS[b].month;
    return a - b;
  });
  reorderContainer($("field-cards"), target);
  for (const id of target) {
    const el = cardEl(id);
    el.classList.remove("flipped", "playable", "pending", "dimmed", "highlight-match", "just-drawn");
    el.style.visibility = "";
  }
  if (st.pending_card != null) {
    cardEl(st.pending_card).classList.add("pending");
    pendingCardId = st.pending_card;
  } else {
    pendingCardId = null;
  }
}

function reconcileHand(st) {
  const target = [...st.hand].sort((a, b) => {
    if (CARDS[a].month !== CARDS[b].month) return CARDS[a].month - CARDS[b].month;
    return a - b;
  });
  reorderContainer($("hand-cards"), target);
  for (const id of target) {
    const el = cardEl(id);
    el.classList.remove("flipped", "selectable", "pending", "dimmed", "highlight-match", "just-drawn");
    el.style.visibility = "";
  }
}

function reconcileOppHand(st) {
  const container = $("opp-hand-cards");
  const target = st.opponent_hand_count;
  // Remove extras
  while (oppHandBacks.length > target) {
    const b = oppHandBacks.shift();
    if (b && b.parentElement === container) b.remove();
  }
  // Also remove stray back elements not tracked
  const currBacks = [...container.children].filter(c => c.classList.contains("opp-back"));
  for (const b of currBacks) {
    if (!oppHandBacks.includes(b)) b.remove();
  }
  while (oppHandBacks.length < target) {
    const el = makeOppBackEl();
    oppHandBacks.push(el);
    container.appendChild(el);
  }
  // Ensure all tracked backs are mounted
  for (const b of oppHandBacks) {
    if (b.parentElement !== container) container.appendChild(b);
  }
}

function reconcileCaptured(st) {
  reconcileCapSide("player-captured", st.player_captured);
  reconcileCapSide("opponent-captured", st.opponent_captured);
}

function reconcileCapSide(containerId, ids) {
  ensureCapturedStructure(containerId);
  const container = $(containerId);
  const idSet = new Set(ids);

  // Remove cards currently in this side that don't belong here anymore
  for (const el of [...container.querySelectorAll(".card")]) {
    const cid = Number(el.dataset.cardId);
    if (!idSet.has(cid)) el.remove();
  }

  // Ensure each target card is in its matching row
  for (const id of ids) {
    const el = cardEl(id);
    const type = CARDS[id].card_type;
    const row = capRow(containerId, type);
    if (el.parentElement !== row) row.appendChild(el);
    el.classList.remove("flipped", "selectable", "playable", "pending", "dimmed", "highlight-match", "just-drawn");
    el.style.visibility = "";
  }

  // Sort each row by month
  for (const t of CAP_TYPES) {
    const row = capRow(containerId, t);
    const kids = [...row.children].sort((a, b) => {
      const ma = CARDS[Number(a.dataset.cardId)].month;
      const mb = CARDS[Number(b.dataset.cardId)].month;
      if (ma !== mb) return ma - mb;
      return Number(a.dataset.cardId) - Number(b.dataset.cardId);
    });
    for (const k of kids) row.appendChild(k);
  }

  updateCapLabels(containerId);
}

// ================================================================
// Header / interactivity
// ================================================================

function renderHeader() {
  if (!state) return;
  $("round-info").textContent = `${state.round}/${state.total_rounds}局`;
  $("score-info").textContent = `[あなた ${state.scores[0]} - ${state.scores[1]} 相手]`;
}

function renderPhaseMessage() {
  let msg = "";
  if (state.done) {
    if (state.winner === 0) msg = "あなたの勝ち!";
    else if (state.winner === 1) msg = "相手の勝ち";
    else msg = "引き分け";
  } else if (state.phase === "KOIKOI") {
    msg = "";
  } else if (state.current_player === 1 || (state.transitions && state.transitions.length && state.phase !== "HAND_PLAY")) {
    msg = "";
  } else {
    msg = PHASE_MSG[state.phase] || "";
  }
  $("phase-message").textContent = msg;
}

function renderDeckCount(n) {
  visibleDeckCount = n;
  $("deck-count").textContent = n;
  $("deck-display").classList.toggle("hidden", n === 0);
}

function renderYakuInfo() {
  $("player-yaku-info").textContent = formatYaku(state.player_yaku);
  $("opp-yaku-info").textContent = formatYaku(state.opponent_yaku);
}

function formatYaku(yakuList) {
  if (!yakuList || yakuList.length === 0) return "";
  return yakuList.map(([name, pts]) => `${name}(${pts}点)`).join(" ");
}

function applyInteractivity(st) {
  // Clear all interactivity on all known card elements
  for (const id in cardEls) {
    const el = cardEls[id];
    el.classList.remove("selectable", "playable", "dimmed", "highlight-match");
    el.onclick = null;
    el.onmouseenter = null;
    el.onmouseleave = null;
  }
  if (!st || st.done) return;
  if (st.current_player !== 0) return;

  const legal = new Set(st.legal_actions);

  if (st.phase === "HAND_PLAY") {
    const fieldMonths = new Set(st.field.map(id => CARDS[id].month));
    for (const id of st.hand) {
      if (!legal.has(id)) continue;
      const el = cardEl(id);
      const hasMatch = fieldMonths.has(CARDS[id].month);
      if (hasMatch) el.classList.add("selectable");
      else el.classList.add("playable");
      el.onclick = () => doAction(id);
      el.onmouseenter = () => highlightFieldMatches(id);
      el.onmouseleave = clearFieldHighlight;
    }
  } else if (st.phase === "HAND_MATCH" || st.phase === "DRAW_MATCH") {
    for (const id of st.field) {
      if (!legal.has(id)) continue;
      const el = cardEl(id);
      el.classList.add("selectable");
      el.onclick = () => doAction(id);
    }
  }
}

function highlightFieldMatches(handId) {
  const month = CARDS[handId].month;
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

// ================================================================
// Modals
// ================================================================

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
  const yakuStr = (yaku && yaku.length > 0)
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

// ================================================================
// Kifu
// ================================================================

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

// ================================================================
// Util
// ================================================================

function $(id) { return document.getElementById(id); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
