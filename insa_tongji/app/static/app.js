"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const STEPS = ["① 자료", "② 양식", "③ 검증", "④ 생성", "⑤ 결과"];
const state = { people: [], filter: "all", selected: new Set(), step: 1, templatesReady: false, picked: new Set(),
  view: { row: null, url: null, mode: "" }, canRender: false };
const $ = (id) => document.getElementById(id);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(kid ?? ""));
  return el;
}

function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  t.style.display = "block";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.style.display = "none"), isErr ? 7000 : 3500);
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "X-Session-Token": TOKEN, ...(opts.headers || {}) } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || "요청 실패");
  }
  return res;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) }).then((r) => r.json());

async function download(path, fallback) {
  try {
    const res = await api(path);
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*=UTF-8''(.+)$/);
    const name = m ? decodeURIComponent(m[1]) : fallback;
    const url = URL.createObjectURL(await res.blob());
    const a = h("a", { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { toast(e.message, true); }
}

function showStep(n) {
  state.step = n;
  document.querySelectorAll(".step").forEach((s) => s.classList.toggle("show", Number(s.dataset.step) === n));
  $("steps").querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", i + 1 === n));
}

function buildSteps() {
  STEPS.forEach((label, i) => $("steps").append(h("button", { onclick: () => showStep(i + 1) }, label)));
  showStep(1);
}

function clearResults() {
  ["genStatus", "genSummary", "downloads", "resultList"].forEach((id) => $(id).replaceChildren());
  state.picked = new Set();
  closeViewer();
}

function applySettings(s) {
  $("dateMode").value = s.date_mode;
  $("dateStyle").value = s.date_style;
  $("josaFix").checked = s.josa_fix;
  $("fixedDate").value = s.fixed_date;
}

async function refreshPrecheck() {
  const p = await (await api("/api/precheck")).json();
  state.templatesReady = Boolean(p.templates["신규"] && p.templates["전보"]);
  state.canRender = p.can_render;
  applySettings(p.settings);
  $("version").textContent = "v" + p.version;
  document.title = "인사발령장 자동생성기 v" + p.version;
  const item = (ok, text) => h("span", { class: "pre-item" }, h("span", { class: "dot" + (ok ? " ok" : "") }), text);
  $("precheck").replaceChildren(
    item(true, "오프라인(외부 전송 없음)"),
    item(p.hancom, p.hancom ? "한컴오피스 감지(화면 보기·출력 가능)" : "한컴오피스 없음(HWPX 생성·다운로드만 가능)"),
    item(Boolean(p.templates["신규"]), "신규 양식 " + (p.templates["신규"] ? "등록됨" : "미등록")),
    item(Boolean(p.templates["전보"]), "전보 양식 " + (p.templates["전보"] ? "등록됨" : "미등록")),
    item(p.collisions.length === 0, p.collisions.length ? "학교 약칭 충돌 " + p.collisions.length + "건" : "학교 약칭 충돌 없음"),
  );
  for (const kind of ["신규", "전보"]) {
    const t = p.templates[kind];
    $("tpl-" + kind).textContent = t ? "등록됨 · 필드: " + Object.entries(t.fields).map(([k, v]) => k + "×" + v).join(", ") : "";
  }
}

const COLORS = { navy: "#1d3b63", blue: "#2f5f9e", mid: "#5b8dc9", light: "#8fb4e0", pale: "#c3d8f0",
  ok: "#1f8f72", warn: "#d99a2b", err: "#cf4f4f" };
const CODE_LABEL = { V01: "구분 오류", V02: "필수값 없음", V03: "현임교 없음", V04: "신규에 현임교", V05: "현임교=발령교",
  V06: "날짜 오류", V07: "날짜 불일치", V08: "날짜 범위 밖", V09: "중복 행", V10: "동명이인", V11: "학교명 미확정",
  V12: "조사 교정 불가", V13: "길이 경고", V14: "{{ }} 포함", V15: "양식 필수값" };
const pct = (n, t) => (t ? Math.round((n / t) * 100) : 0);

function gcard(cls, title, ...body) {
  return h("section", { class: "gcard " + cls }, h("h3", {}, title), ...body);
}

function kpi(label, value, sub, tone) {
  return h("div", { class: "gcard kpi " + (tone || "") }, h("span", { class: "k-label" }, label),
    h("b", {}, String(value)), sub ? h("span", { class: "chip" }, sub) : "");
}

function donut(parts, centerValue, centerLabel) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  let acc = 0;
  const stops = parts.map((p) => {
    const from = (acc / total) * 100;
    acc += p.value;
    return `${p.color} ${from}% ${(acc / total) * 100}%`;
  });
  const ring = h("div", { class: "donut" }, h("div", { class: "donut-hole" }, h("b", {}, String(centerValue)), h("span", {}, centerLabel)));
  ring.style.background = total ? `conic-gradient(${stops.join(",")})` : "#e3ebf6";
  const legend = h("div", { class: "legend" }, parts.map((p) => {
    const dot = h("i");
    dot.style.background = p.color;
    return h("div", {}, dot, p.label, h("em", {}, `${p.value}명 · ${pct(p.value, total)}%`));
  }));
  return h("div", { class: "donut-wrap" }, ring, legend);
}

function bars(items, emptyText) {
  if (!items.length) return h("div", { class: "empty" }, emptyText);
  const max = Math.max(...items.map((i) => i.value));
  return h("div", { class: "bars" }, items.map((i) => {
    const fill = h("div", { class: "bar-fill " + (i.tone || "") });
    fill.style.width = Math.max(4, Math.round((i.value / max) * 100)) + "%";
    return h("div", { class: "bar-row" }, h("span", { class: "bar-label", title: i.label }, i.label),
      h("div", { class: "bar-track" }, fill), h("span", { class: "bar-val" }, String(i.value)));
  }));
}

function tally(values) {
  const counts = new Map();
  values.filter(Boolean).forEach((v) => counts.set(v, (counts.get(v) || 0) + 1));
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko"));
}

function resultGauge(people) {
  const done = people.filter((p) => p.status);
  if (!done.length) return h("div", { class: "empty" }, "아직 생성하지 않았습니다. ④ 생성 단계에서 통지서를 만들면 결과가 표시됩니다.");
  const n = (s) => done.filter((p) => p.status === s).length;
  const parts = [["PASS", COLORS.ok, "생성 성공"], ["FAIL", COLORS.err, "생성 실패"], ["SKIP", COLORS.light, "검증 오류로 제외"]];
  const gauge = h("div", { class: "gauge" }, parts.map(([s, color]) => {
    const seg = h("span");
    seg.style.width = pct(n(s), done.length) + "%";
    seg.style.background = color;
    return seg;
  }));
  const legend = h("div", { class: "legend" }, parts.map(([s, color, label]) => {
    const dot = h("i");
    dot.style.background = color;
    return h("div", {}, dot, label, h("em", {}, `${n(s)}건`));
  }));
  return h("div", {}, gauge, legend);
}

function renderDash(data) {
  const people = data.people || [];
  const board = $("board");
  board.hidden = !people.length;
  if (!people.length) return;
  const total = people.length;
  const okPeople = people.filter((p) => p.ok);
  const cleanCount = okPeople.filter((p) => !p.issues.some((i) => i.level === "경고")).length;
  const warnCount = okPeople.length - cleanCount;
  const badCount = total - okPeople.length;
  const newCount = people.filter((p) => p.kind === "신규").length;
  const transferCount = people.filter((p) => p.kind === "전보").length;
  const issueCounts = tally(people.flatMap((p) => [...new Set(p.issues.map((i) => i.code))]));
  const levelOf = (code) => people.flatMap((p) => p.issues).find((i) => i.code === code).level;
  const toneOf = { 오류: "err", 경고: "warn", 정보: "info" };

  board.replaceChildren(
    kpi("전체 대상자", total, "엑셀 기준"),
    kpi("신규 임용", newCount, pct(newCount, total) + "%"),
    kpi("전보", transferCount, pct(transferCount, total) + "%"),
    kpi("확인 필요", badCount, badCount ? "생성에서 제외됨" : "없음", badCount ? "bad" : "good"),
    gcard("span4", "구분별 구성", donut([
      { label: "신규", value: newCount, color: COLORS.blue },
      { label: "전보", value: transferCount, color: COLORS.light },
      { label: "기타·오류", value: total - newCount - transferCount, color: COLORS.warn },
    ].filter((p) => p.value || p.label !== "기타·오류"), total, "명")),
    gcard("span4", "검증 상태", donut([
      { label: "정상", value: cleanCount, color: COLORS.ok },
      { label: "경고(생성 가능)", value: warnCount, color: COLORS.warn },
      { label: "오류(제외)", value: badCount, color: COLORS.err },
    ], pct(okPeople.length, total) + "%", "생성 가능")),
    gcard("span4", "생성 결과", resultGauge(people)),
    gcard("span4", "직종별 인원", bars(tally(people.map((p) => p.job)).slice(0, 6).map(([label, value]) => ({ label, value })), "직종 정보가 없습니다.")),
    gcard("span4", "발령교 상위", bars(tally(people.map((p) => p.new_school)).slice(0, 6).map(([label, value]) => ({ label, value })), "발령교 정보가 없습니다.")),
    gcard("span4", "검증 항목별 건수", bars(issueCounts.slice(0, 7).map(([code, value]) => ({
      label: `${code} ${CODE_LABEL[code] || ""}`, value, tone: toneOf[levelOf(code)] })), "발견된 오류·경고가 없습니다.")),
  );
  const now = new Date();
  $("updated").textContent = `이 PC에서만 처리됩니다 · 마지막 갱신 ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

async function uploadExcel(file) {
  try {
    const data = await (await api("/api/excel", { method: "POST", body: await file.arrayBuffer() })).json();
    state.people = data.people;
    state.selected = new Set(data.people.filter((p) => p.ok).map((p) => p.row));
    clearResults(); renderDash(data); renderPeople(); await refreshPrecheck();
    toast(`${data.total}명을 불러왔습니다.`);
    showStep(state.templatesReady ? 3 : 2);
  } catch (e) { toast(e.message, true); }
}

async function uploadTemplate(kind, file) {
  try {
    await api("/api/template?kind=" + encodeURIComponent(kind), { method: "POST", body: await file.arrayBuffer() });
    clearResults(); await refreshPrecheck();
    toast(kind + " 양식을 등록했습니다.");
  } catch (e) { toast(e.message, true); }
}

function setupDrop(zone, input, handler) {
  input.addEventListener("change", () => input.files[0] && handler(input.files[0]));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); e.dataTransfer.files[0] && handler(e.dataTransfer.files[0]); });
}

function matches(p) {
  if (state.filter === "all") return true;
  if (state.filter === "bad") return !p.ok;
  if (state.filter === "warn") return p.issues.some((i) => i.level === "경고");
  return p.issues.some((i) => i.code === state.filter);
}

function refreshAfterChange(data) {
  state.people = data.people;
  state.selected = new Set(data.people.filter((p) => p.ok).map((p) => p.row));
  clearResults(); renderDash(data); renderPeople();
}

async function edit(row, field, value) {
  try {
    const data = await post("/api/edit", { edits: [{ row, field, value }], choices: [] });
    refreshAfterChange(data);
  } catch (e) { toast(e.message, true); }
}

async function choose(row, field, value, saveAlias) {
  if (!value.trim()) return toast("학교명을 선택하거나 입력하세요.", true);
  try {
    const data = await post("/api/edit", { edits: [], choices: [{ row, field, value }], save_alias: saveAlias });
    refreshAfterChange(data);
    if (data.notice) toast(data.notice, true);
  } catch (e) { toast(e.message, true); }
}

function cellInput(p, field, value) {
  const input = h("input", { type: "text", value: value || "", class: field === "성명" ? "nm" : "" });
  input.addEventListener("change", () => edit(p.row, field, input.value));
  return input;
}

function schoolCell(p, field, value) {
  const wrap = h("div", {}, cellInput(p, field, value));
  const m = p.match[field];
  if (m && !["exact", "alias", "auto", "selected", "manual"].includes(m.status)) {
    const sel = h("select", {}, h("option", { value: "" }, m.candidates.length ? "후보 선택" : "후보 없음"),
      m.candidates.map((c) => h("option", { value: c }, c)));
    const manual = h("input", { type: "text", placeholder: "공식 학교명 직접 입력" });
    const alias = h("input", { type: "checkbox" });
    const apply = h("button", { class: "ghost", onclick: () => choose(p.row, field, manual.value || sel.value, alias.checked) }, "적용");
    wrap.append(h("div", { class: "cand" }, sel, manual, h("label", {}, alias, "별칭 저장"), apply));
  }
  return wrap;
}

function renderPeople() {
  const filters = [["all", "전체"], ["bad", "확인 필요"], ["warn", "경고"], ["V11", "학교명"], ["V03", "현임교 없음"], ["V06", "날짜"]];
  $("filters").replaceChildren(...filters.map(([k, label]) =>
    h("button", { class: state.filter === k ? "on" : "", onclick: () => { state.filter = k; renderPeople(); } }, label)));
  const head = h("tr", {}, ["선택", "행", "구분", "직종", "성명", "현임교", "발령교", "발령일", "상태"].map((t) => h("th", {}, t)));
  const rows = state.people.filter(matches).map((p) => {
    const sel = h("input", { type: "checkbox", checked: state.selected.has(p.row) && p.ok, disabled: !p.ok });
    sel.addEventListener("change", () => (sel.checked ? state.selected.add(p.row) : state.selected.delete(p.row)));
    const badges = p.issues.map((i) => h("span", { class: "badge " + i.level, title: i.message }, i.code));
    const date = h("input", { type: "text", value: p.date });
    date.addEventListener("change", () => edit(p.row, "발령일", date.value));
    return h("tr", { class: p.ok ? "" : "bad" },
      h("td", {}, sel), h("td", {}, String(p.row)),
      h("td", {}, cellInput(p, "구분", p.kind)), h("td", {}, cellInput(p, "직종", p.job)),
      h("td", {}, cellInput(p, "성명", p.name)),
      h("td", {}, p.kind === "전보" ? schoolCell(p, "현임교", p.cur_school) : "—"),
      h("td", {}, schoolCell(p, "발령교", p.new_school)), h("td", {}, date),
      h("td", {}, badges.length ? badges : h("span", { class: "badge PASS" }, "정상")));
  });
  $("people").replaceChildren(h("thead", {}, head), h("tbody", {}, rows));
}

function closeViewer() {
  if (state.view.url) URL.revokeObjectURL(state.view.url);
  state.view = { row: null, url: null, mode: "" };
  $("viewer").hidden = true;
  $("viewerEmpty").hidden = false;
  $("vBody").replaceChildren();
}

const passRows = () => state.people.filter((p) => p.status === "PASS").map((p) => p.row);

function viewerMessage(text, spinner) {
  $("vBody").replaceChildren(h("div", { class: "viewer-msg" }, spinner ? h("div", { class: "spinner" }) : "", text));
}

async function openViewer(row) {
  const person = state.people.find((p) => p.row === row);
  if (!person) return;
  if (state.view.url) URL.revokeObjectURL(state.view.url);
  state.view = { row, url: null, mode: "" };
  $("viewer").hidden = false;
  $("viewerEmpty").hidden = true;
  $("vTitle").replaceChildren(`${person.kind} · ${person.job} · `, h("span", { class: "nm" }, person.name));
  $("vNote").textContent = "";
  $("vPrint").disabled = true;
  renderResultList();
  viewerMessage("한컴오피스로 문서를 만드는 중입니다…(처음 한 번은 몇 초 걸립니다)", true);
  try {
    const blob = await (await api("/api/render?row=" + row)).blob();
    if (state.view.row !== row) return;
    state.view.url = URL.createObjectURL(blob);
    state.view.mode = "pdf";
    $("vBody").replaceChildren(h("iframe", { src: state.view.url, title: "생성된 통지서" }));
    $("vPrint").disabled = false;
    $("vNote").textContent = "실제 서식(직인·표 포함) 그대로의 모양입니다. 괜찮으면 다운로드하거나 출력하세요.";
  } catch (e) {
    if (state.view.row === row) await showTextFallback(row, e.message);
  }
}

async function showTextFallback(row, reason) {
  state.view.mode = "text";
  try {
    const d = await (await api("/api/preview?row=" + row)).json();
    $("vBody").replaceChildren(h("div", { class: "viewer-text" },
      h("div", {}, h("h3", {}, "양식(치환 전)"), h("pre", { class: "pv" }, d.before)),
      h("div", {}, h("h3", {}, "생성된 본문(치환 후)"), h("pre", { class: "pv" }, d.after))));
    $("vNote").textContent = `${reason} 지금은 실제 모양 대신 본문 글자만 보여줍니다. 출력은 다운로드한 HWPX를 한컴오피스에서 열어서 하세요.`;
  } catch (e) {
    viewerMessage(e.message);
  }
}

function stepViewer(delta) {
  const rows = passRows();
  if (!rows.length) return;
  const idx = rows.indexOf(state.view.row);
  openViewer(rows[(idx + delta + rows.length) % rows.length]);
}

function printViewer() {
  const frame = $("vBody").querySelector("iframe");
  if (state.view.mode !== "pdf" || !frame) return toast("출력은 실제 모양(PDF)이 표시된 문서에서만 할 수 있습니다.", true);
  try {
    frame.contentWindow.focus();
    frame.contentWindow.print();
  } catch (e) {
    window.open(state.view.url, "_blank");
    toast("새 창에서 PDF가 열렸습니다. 그 창에서 인쇄하세요.");
  }
}

async function generate() {
  $("generate").disabled = true;
  try {
    const scope = $("scope").value;
    const d = await post("/api/generate", { scope, rows: [...state.selected] });
    state.people = d.people; renderPeople(); renderResult(d); renderDash({ people: d.people }); showStep(5);
    const first = passRows()[0];
    if (first !== undefined) openViewer(first);
  } catch (e) { toast(e.message, true); } finally { $("generate").disabled = false; }
}

function renderResult(d) {
  const c = d.counts;
  state.picked = new Set(passRows());
  $("genSummary").replaceChildren(h("div", { class: "dash-inline" },
    `생성 성공 ${c.PASS}건 · 실패 ${c.FAIL}건 · 검증 오류로 제외 ${c.SKIP}건` + (d.josa_fixed ? ` · 조사 교정 ${d.josa_fixed}건` : "")));
  $("genStatus").replaceChildren();
  $("downloads").replaceChildren(
    h("button", { class: "primary", id: "zipSelected", onclick: downloadSelected }, ""),
    h("button", { onclick: () => download("/api/download/zip", "인사발령통지서.zip") }, "전체 ZIP 저장"),
    h("button", { onclick: () => download("/api/download/ledger", "처리결과.xlsx") }, "처리결과 엑셀"),
    h("button", { onclick: () => download("/api/download/errors", "오류목록.xlsx") }, "오류 목록 엑셀"));
  renderResultList();
}

function updateZipButton() {
  const btn = $("zipSelected");
  if (!btn) return;
  btn.textContent = `확인한 ${state.picked.size}건 ZIP 다운로드`;
  btn.disabled = state.picked.size === 0;
}

function downloadSelected() {
  download("/api/download/zip?rows=" + [...state.picked].join(","), "인사발령통지서(선택).zip");
}

function renderResultList() {
  const done = state.people.filter((p) => p.status);
  const allPass = passRows();
  const master = h("input", { type: "checkbox", checked: allPass.length > 0 && allPass.every((r) => state.picked.has(r)), "aria-label": "전체 선택" });
  master.addEventListener("change", () => {
    state.picked = master.checked ? new Set(allPass) : new Set();
    renderResultList();
  });
  const rows = done.map((p) => {
    const pick = h("input", { type: "checkbox", checked: state.picked.has(p.row), disabled: p.status !== "PASS" });
    pick.addEventListener("click", (e) => e.stopPropagation());
    pick.addEventListener("change", () => {
      if (pick.checked) state.picked.add(p.row); else state.picked.delete(p.row);
      updateZipButton();
    });
    const tr = h("tr", { class: state.view.row === p.row ? "sel" : "" },
      h("td", { class: "pick" }, pick), h("td", {}, String(p.row)), h("td", {}, p.kind),
      h("td", { class: "nm" }, p.name), h("td", {}, h("span", { class: "badge " + p.status }, p.status)),
      h("td", {}, p.status === "PASS" ? h("button", { class: "ghost", type: "button", onclick: () => openViewer(p.row) }, "보기") : ""));
    return tr;
  });
  $("resultList").replaceChildren(h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, master), ["행", "구분", "성명", "결과", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows)));
  updateZipButton();
}

async function saveSettings() {
  try {
    const data = await post("/api/settings", {
      date_mode: $("dateMode").value, date_style: $("dateStyle").value,
      josa_fix: $("josaFix").checked, fixed_date: $("dateMode").value === "fixed" ? $("fixedDate").value : "",
    });
    clearResults();
    if (data.people) refreshAfterChange(data);
    toast("설정을 적용했습니다.");
  } catch (e) { toast(e.message, true); }
}

function init() {
  if (!TOKEN) { document.body.textContent = "프로그램이 열어 준 주소(토큰 포함)로 접속해 주세요."; return; }
  buildSteps();
  setupDrop($("dropExcel"), $("fileExcel"), uploadExcel);
  document.querySelectorAll(".tplfile").forEach((input) => setupDrop(input.parentElement, input, (f) => uploadTemplate(input.dataset.kind, f)));
  $("generate").addEventListener("click", generate);
  $("vPrev").addEventListener("click", () => stepViewer(-1));
  $("vNext").addEventListener("click", () => stepViewer(1));
  $("vPrint").addEventListener("click", printViewer);
  $("vDownload").addEventListener("click", () => state.view.row !== null && download("/api/download/file?row=" + state.view.row, "통지서.hwpx"));
  $("saveSettings").addEventListener("click", saveSettings);
  setupReset();
  $("mask").addEventListener("change", (e) => document.body.classList.toggle("masked", e.target.checked));
  refreshPrecheck().then(restoreSession).catch((e) => toast(e.message, true));
}

async function resetAll(withTemplates) {
  try {
    await post("/api/reset", { templates: withTemplates });
    state.people = [];
    state.selected = new Set();
    state.filter = "all";
    document.querySelectorAll("input[type=file]").forEach((input) => { input.value = ""; });
    clearResults(); renderDash({ people: [] }); renderPeople();
    $("updated").textContent = "이 PC에서만 처리됩니다";
    await refreshPrecheck();
    showStep(1);
    toast(withTemplates ? "작업 내용과 등록한 양식을 모두 지웠습니다." : "작업 내용을 지웠습니다. 등록한 양식은 유지됩니다.");
  } catch (e) { toast(e.message, true); }
}

function setupReset() {
  const dialog = $("resetDialog");
  $("reset").addEventListener("click", () => { $("resetTemplates").checked = false; dialog.showModal(); });
  dialog.addEventListener("close", () => {
    if (dialog.returnValue === "ok") resetAll($("resetTemplates").checked);
    dialog.returnValue = "";
  });
}

async function restoreSession() {
  const data = await (await api("/api/people")).json();
  if (!data.people.length) return;
  state.people = data.people;
  state.selected = new Set(data.people.filter((p) => p.ok).map((p) => p.row));
  renderDash(data); renderPeople();
  if (!data.people.some((p) => p.status)) return;
  renderResult(await (await api("/api/results")).json());
  showStep(5);
}
init();
