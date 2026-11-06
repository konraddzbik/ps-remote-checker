// PS Remote Helper panel. All server data is inserted with textContent (never innerHTML).
"use strict";

const $ = (id) => document.getElementById(id);
const LEVEL_ICON = { ok: "✓", warn: "!", fail: "✕" };
const NAT = {
  open: ["Type 1", "Open, no NAT", "ok"],
  eim: ["Type 2", "Cone NAT", "ok"],
  symmetric: ["Type 3", "Symmetric (strict)", "warn"],
  udp_blocked: ["Blocked", "UDP blocked", "fail"],
};
let last = null;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}

function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleString();
}

function chip(node, level, text) {
  node.className = "chip " + (level || "");
  node.replaceChildren(el("span", "dot"), el("span", null, text));
}

function tile(key, value, detail, level) {
  const t = el("div", "tile " + (level || ""));
  const k = el("div", "k");
  k.append(el("span", null, key));
  if (level) k.append(el("span", "ic " + level, LEVEL_ICON[level]));
  t.append(k, el("div", "v", value));
  if (detail) t.append(el("div", "d", detail));
  return t;
}

function mbps(v) { return v == null ? "—" : `${v >= 100 ? Math.round(v) : v.toFixed(1)} Mbps`; }

function renderHome(h, running) {
  const tiles = $("hometiles"), findings = $("homefindings");
  tiles.replaceChildren(); findings.replaceChildren();
  $("selfcheck").disabled = running;
  $("selfcheck").textContent = running ? "Checking…" : "Run self-check now";
  if (!h) {
    chip($("homechip"), "", running ? "running" : "not yet");
    findings.append(el("div", "empty", running ? "The first self-check is running…" : "No self-check yet."));
    $("homeat").textContent = "";
    return;
  }
  const label = { ok: "ready", warn: "needs attention", fail: "problem" }[h.overall] || h.overall;
  chip($("homechip"), h.overall, label);
  $("homeat").textContent = "checked " + ago(h.at);
  const ps5 = h.ps5 || {}, nat = h.nat || {}, up = h.upnp || {}, lat = h.latency || {}, sp = h.speed || {};
  tiles.append(
    tile("PS5", ps5.found ? (ps5.name || "PS5") : "Not found",
         ps5.found ? `${ps5.status === "on" ? "On" : "Rest mode"} · ${ps5.ip}` : "on/rest mode, same LAN?", ps5.found ? "ok" : "warn"),
    tile("NAT type", (NAT[nat.type] || ["Unknown"])[0], (NAT[nat.type] || [, "could not determine"])[1], (NAT[nat.type] || [, , "warn"])[2]),
    tile("Public IP", nat.public_ip || "—", null, null),
    tile("Router / UPnP", !up.found ? "UPnP off" : up.cgnat ? "CGNAT" : up.double_nat ? "Double NAT" :
         (up.ps5_mappings || []).length ? "PS5 ports open" : "UPnP on",
         up.device || "", !up.found || up.cgnat || up.double_nat ? "warn" : "ok"),
    tile("Latency", lat.avg_ms != null ? `${Math.round(lat.avg_ms)} ms` : "—",
         lat.avg_ms != null ? `jitter ${lat.jitter_ms} ms · loss ${lat.loss_pct}%` : null, null),
    tile("Upload", mbps(sp.up_mbps), sp.up_mbps != null ? `download ${mbps(sp.down_mbps)}` : "speed test off",
         sp.up_mbps == null ? null : sp.up_mbps < 5 ? "fail" : sp.up_mbps < 15 ? "warn" : "ok"),
  );
  for (const f of (h.findings || []).filter((f) => f.level !== "ok")) {
    const row = el("div", "finding");
    const body = el("div");
    body.append(el("div", null, f.message));
    if (f.fix) body.append(el("div", "fix", "→ " + f.fix));
    row.append(el("div", "ic " + f.level, LEVEL_ICON[f.level]), body);
    findings.append(row);
  }
}

function sessionResult(s) {
  if (s.status === "running") return ["running…", ""];
  if (s.error) return ["failed", "fail"];
  if (!s.connected) return ["no direct connection", "fail"];
  if (s.path === "lan") return ["local network only", "warn"];
  return ["verified", "ok"];
}

function renderSessions(list) {
  const box = $("sessions");
  box.replaceChildren();
  if (!list.length) {
    box.append(el("div", "empty", "No live tests yet. Run one from away with the pairing code."));
    return;
  }
  const wrap = el("div", "table"), table = el("table"), head = el("tr");
  for (const h of ["When", "From", "Result", "Opened in", "Round trip", "Stream", "Loss"]) head.append(el("th", null, h));
  table.append(head);
  for (const s of list) {
    const tr = el("tr");
    const [text, level] = sessionResult(s);
    const res = el("td"); const c = el("span"); chip(c, level, text); res.append(c);
    tr.append(
      el("td", null, ago(s.ts)), el("td", null, s.from || "—"), res,
      el("td", null, s.punch_ms != null ? `${s.punch_ms} ms` : "—"),
      el("td", null, s.rtt_ms != null ? `${s.rtt_ms} ms` : "—"),
      el("td", null, s.stream_mbps != null ? `${s.stream_mbps} / ${s.target_mbps} Mbps` : "—"),
      el("td", null, s.loss_pct != null ? `${s.loss_pct}%` : "—"),
    );
    table.append(tr);
  }
  wrap.append(table);
  box.append(wrap);
}

function renderLog(events) {
  const box = $("log");
  box.replaceChildren();
  for (const e of events.slice().reverse()) {
    const parts = Object.entries(e).filter(([k]) => k !== "ts" && k !== "event" && k !== "code")
      .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`);
    box.append(el("div", null, `${new Date(e.ts * 1000).toLocaleTimeString()}  ${e.event}  ${parts.join("  ")}`));
  }
}

function render(st) {
  last = st;
  $("code").textContent = st.code;
  $("cmd").textContent = `python3 -m ps_remote_checker remote --pair ${st.code}`;
  $("relay").textContent = "relay: " + new URL(st.relay).host;
  $("newcode").disabled = st.code_locked;
  $("codehint").textContent = st.code_locked
    ? "The code is set in the add-on configuration. Change it there to rotate."
    : "Enter this code on the Away page of the Mac app. Rotating it invalidates the old one immediately.";
  if (st.relay_error) chip($("status"), "warn", "relay unreachable");
  else chip($("status"), "ok", "waiting for tests");
  renderHome(st.home, st.home_running);
  renderSessions(st.sessions || []);
  renderLog(st.events || []);
  $("version").textContent = `PS Remote Helper ${st.version} · up ${Math.round(st.uptime_s / 60)} min`;
}

async function refresh() {
  try {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    render(await r.json());
  } catch (e) {
    chip($("status"), "fail", "panel offline");
  }
}

async function post(path) {
  await fetch(path, { method: "POST", headers: { "X-PSRC": "1" } });
  setTimeout(refresh, 400);
}

$("selfcheck").addEventListener("click", () => post("api/selfcheck"));
$("newcode").addEventListener("click", () => {
  if (confirm("Create a new pairing code? The old one stops working.")) post("api/newcode");
});
$("copy").addEventListener("click", async () => {
  if (!last) return;
  try { await navigator.clipboard.writeText(last.code); $("copy").textContent = "Copied"; }
  catch { getSelection().selectAllChildren($("code")); $("copy").textContent = "Press ⌘C"; }
  setTimeout(() => ($("copy").textContent = "Copy"), 2000);
});

refresh();
setInterval(refresh, 3000);
