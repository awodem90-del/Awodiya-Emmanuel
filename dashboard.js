const statusPill = document.getElementById("status-pill");
const marketPill = document.getElementById("market-pill");
const sessionPill = document.getElementById("session-pill");
const bestContent = document.getElementById("best-content");
const pairsGrid = document.getElementById("pairs-grid");
const lastScan = document.getElementById("last-scan");
const historyList = document.getElementById("history-list");

const TIER_CLASS = {
  VERY_HIGH: "tier-verylow-hi",
  HIGH: "tier-high",
  MEDIUM: "tier-medium",
  LOW: "tier-low",
  VERY_LOW: "tier-verylow",
};

function fmt(n, digits = 5) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

function directionBadge(direction) {
  if (direction === "HIGHER") return `<span class="direction-badge HIGHER">🟢 HIGHER ⬆️</span>`;
  return `<span class="direction-badge LOWER">🔴 LOWER ⬇️</span>`;
}

function tierClass(tier) {
  return TIER_CLASS[tier] || "tier-medium";
}

function renderBest(best) {
  if (!best) {
    bestContent.innerHTML = `<p class="empty">No data yet — the assistant keeps scanning continuously and will show the best available setup here.</p>`;
    return;
  }
  const reasons = (best.reasons || []).map((r) => `<li>✅ ${r}</li>`).join("");
  const staleNote = best.stale
    ? `<p class="stale-note">⚠️ Live feed unavailable (weekend/OTC gap) — showing the last known market read.</p>`
    : "";
  bestContent.innerHTML = `
    <div class="alert-headline">
      <span class="pair">${best.display_pair || best.pair}</span>
      ${directionBadge(best.direction)}
      <span class="confidence">${best.confidence}% confidence</span>
      <span class="tier-badge ${tierClass(best.tier)}">${best.tier_emoji || ""} ${best.tier_label || ""}</span>
    </div>
    <div class="meta-row">
      <span>⏱ Expiry: <strong>${best.expiry}</strong></span>
      <span>📍 Entry: <strong>${best.entry_time}</strong></span>
      <span>📈 Trend: <strong>${best.trend || ""}</strong></span>
      <span>🗺 Session: <strong>${best.session || "—"}</strong></span>
      <span>Sent to Telegram: <strong>${best.sent ? "Yes" : "No"}</strong></span>
    </div>
    <ul class="reasons">${reasons}</ul>
    ${best.summary ? `<p class="muted">${best.summary}</p>` : ""}
    <div class="decision-row">
      <span class="decision-badge decision-${(best.final_decision || "").toLowerCase()}">${best.final_decision_display || ""}</span>
      <span class="recommendation">${best.recommendation || ""}</span>
    </div>
    ${staleNote}
  `;
}

function renderPairs(evaluations) {
  pairsGrid.innerHTML = "";
  for (const e of evaluations) {
    const card = document.createElement("div");
    card.className = "pair-card";
    card.innerHTML = `
      <div class="pair-name"><span>${e.pair}</span>${directionBadge(e.direction)}</div>
      <div class="row"><span>Confidence</span><span class="tier-text ${tierClass(e.tier)}">${e.confidence}% · ${e.tier_emoji || ""} ${e.tier_label || ""}</span></div>
      <div class="row"><span>Price</span><span>${fmt(e.price)}</span></div>
      <div class="row"><span>RSI(7)</span><span>${fmt(e.rsi, 1)} · ${e.rsi_label || ""}</span></div>
      <div class="row"><span>EMA 20/50/200</span><span>${fmt(e.ema20)} / ${fmt(e.ema50)} / ${fmt(e.ema200)}</span></div>
      <div class="row"><span>MACD</span><span>${e.macd_label || fmt(e.macd, 5)}</span></div>
      <div class="row"><span>Structure</span><span>${e.market_structure || "—"}</span></div>
      <div class="row"><span>Candle Pattern</span><span>${e.candle_pattern || "—"}</span></div>
      <div class="row"><span>Expiry</span><span>${e.expiry}</span></div>
      <div class="row"><span>Continuation / Reversal</span><span>${e.continuation_probability ?? "—"}% / ${e.reversal_probability ?? "—"}%</span></div>
      <div class="row decision-line"><span>${e.final_decision_display || ""}</span></div>
    `;
    pairsGrid.appendChild(card);
  }
}

function renderHistory(history) {
  if (!history || history.length === 0) {
    historyList.innerHTML = `<div class="history-empty">No signals sent yet.</div>`;
    return;
  }
  historyList.innerHTML = history
    .slice()
    .reverse()
    .map((h) => {
      const time = new Date(h.generated_at).toLocaleString();
      return `<div class="history-item">
        <div class="h-left"><strong>${h.display_pair || h.pair}</strong> ${directionBadge(h.direction)} ${h.confidence}%</div>
        <div>${time}</div>
      </div>`;
    })
    .join("");
}

async function refresh() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();

    if (!data.telegram_configured || !data.data_configured) {
      statusPill.textContent = "configuration incomplete";
      statusPill.className = "status err";
    } else if (data.last_error) {
      statusPill.textContent = "scan error — see below";
      statusPill.className = "status err";
    } else {
      statusPill.textContent = "live";
      statusPill.className = "status ok";
    }

    if (data.market_open) {
      marketPill.textContent = "🟢 live feed";
      marketPill.className = "status ok";
    } else {
      marketPill.textContent = "🟡 OTC (weekend)";
      marketPill.className = "status warn";
    }

    sessionPill.textContent = `🗺 ${data.market_session || "—"}`;
    sessionPill.className = "status";

    lastScan.textContent = data.last_scan_at
      ? `· last scan ${new Date(data.last_scan_at).toLocaleTimeString()}${data.stale ? " (stale/OTC)" : ""}`
      : "";

    renderBest(data.best);
    renderPairs(data.evaluations || []);

    const histRes = await fetch("/api/history");
    renderHistory(await histRes.json());
  } catch (e) {
    statusPill.textContent = "offline";
    statusPill.className = "status err";
  }
}

refresh();
setInterval(refresh, 15000);
