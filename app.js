/* ═══════════════════════════════════════════════════
   PC STOCKS — App Logic
   Real price tracking from Python backend + alerts
   ═══════════════════════════════════════════════════ */

// ────────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────────
const API_BASE = window.location.origin;
const REFRESH_INTERVAL = 60_000; // Poll API every 60 seconds

// ────────────────────────────────────────────────────
// STATE
// ────────────────────────────────────────────────────
let PARTS = [];
let alerts = {};
let currentView = "dashboard";
let sparkCharts = {};
let totalChartInst = null;
let lastScrapeInfo = null;

// ────────────────────────────────────────────────────
// API CALLS
// ────────────────────────────────────────────────────
async function fetchPrices() {
  try {
    const resp = await fetch(`${API_BASE}/api/prices`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    PARTS = data.parts || [];
    lastScrapeInfo = data.lastScrape || null;

    // Load alert targets from the data
    PARTS.forEach((p) => {
      if (p.alertTarget !== undefined && alerts[p.id] === undefined) {
        alerts[p.id] = p.alertTarget;
      }
    });

    return true;
  } catch (e) {
    console.warn("Failed to fetch prices:", e);
    return false;
  }
}

async function triggerScrape() {
  const btn = document.getElementById("scrapeBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Scraping...";
  }

  try {
    const resp = await fetch(`${API_BASE}/api/scrape`, { method: "POST" });
    const data = await resp.json();
    showToast(
      "Scrape Complete",
      `Updated ${data.scrape?.updated || 0} of ${data.scrape?.total || 0} parts`,
      "sale"
    );
    await fetchPrices();
    renderCurrentView();
  } catch (e) {
    showToast("Scrape Failed", String(e), "warn");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Refresh Prices";
    }
  }
}

async function saveAlertToServer(partId, target) {
  try {
    await fetch(`${API_BASE}/api/alerts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ partId, target }),
    });
  } catch (e) {
    console.warn("Failed to save alert:", e);
  }
}

// ────────────────────────────────────────────────────
// HELPERS
// ────────────────────────────────────────────────────
function fmt(n) {
  return "$" + Math.round(n).toLocaleString("en-AU");
}

function fmtDelta(n) {
  const sign = n > 0 ? "+" : "";
  return sign + "$" + Math.abs(Math.round(n));
}

function getDelta(part) {
  const h = part.history || [];
  if (h.length < 2) return 0;
  const weekAgo = h[Math.max(0, h.length - 8)];
  return part.currentPrice - (weekAgo ? weekAgo.price : part.currentPrice);
}

function getBestPrice(part) {
  const h = part.history || [];
  if (h.length === 0) return part.currentPrice;
  return Math.min(...h.map((e) => e.price));
}

function getAlertStatus(part) {
  const target = alerts[part.id] || part.alertTarget;
  if (!target) return null;
  const delta = getDelta(part);
  if (part.currentPrice <= target) return "triggered";
  if (delta > 0) return "rising";
  return "watching";
}

function totalCost() {
  return PARTS.reduce((sum, p) => sum + p.currentPrice, 0);
}

function totalWeekAgo() {
  return PARTS.reduce((sum, p) => {
    const h = p.history || [];
    const weekAgo = h[Math.max(0, h.length - 8)];
    return sum + (weekAgo ? weekAgo.price : p.currentPrice);
  }, 0);
}

function bestTotalEver() {
  return PARTS.reduce((sum, p) => sum + getBestPrice(p), 0);
}

function activeAlertCount() {
  return PARTS.filter((p) => getAlertStatus(p) === "triggered").length;
}

function formatSource(source) {
  if (source === "pcpartpicker") return "PCPartPicker AU";
  if (source === "staticice") return "StaticICE";
  if (source === "fallback") return "Estimated";
  if (source === "seed") return "Initial estimate";
  return source || "Unknown";
}

// ────────────────────────────────────────────────────
// RENDERING — DASHBOARD
// ────────────────────────────────────────────────────
function renderDashboard() {
  if (PARTS.length === 0) return;

  const total = totalCost();
  const weekAgo = totalWeekAgo();
  const weekDelta = total - weekAgo;
  const best = bestTotalEver();
  const alertCount = activeAlertCount();

  document.getElementById("totalCost").textContent = fmt(total);

  const weekEl = document.getElementById("weekDelta");
  weekEl.textContent = fmtDelta(weekDelta);
  weekEl.className =
    "summary-card__value " +
    (weekDelta < 0 ? "positive" : weekDelta > 0 ? "negative" : "");

  document.getElementById("bestTotal").textContent = fmt(Math.round(best));
  document.getElementById("activeAlerts").textContent = alertCount;

  // Last scrape info
  const scrapeInfo = document.getElementById("lastScrapeInfo");
  if (scrapeInfo && lastScrapeInfo) {
    const when = lastScrapeInfo.timestamp
      ? new Date(lastScrapeInfo.timestamp).toLocaleString("en-AU", {
          dateStyle: "short",
          timeStyle: "short",
        })
      : "Never";
    const status =
      lastScrapeInfo.status === "ok"
        ? "✓"
        : lastScrapeInfo.status === "seeded"
        ? "Seeded"
        : "⚠";
    scrapeInfo.textContent = `Last update: ${when} ${status}`;
  }

  // Alert badge
  const badge = document.getElementById("alertBadge");
  badge.textContent = alertCount;
  badge.classList.toggle("zero", alertCount === 0);

  // Parts grid
  const grid = document.getElementById("partsGrid");
  grid.innerHTML = "";

  PARTS.forEach((part) => {
    const delta = getDelta(part);
    const status = getAlertStatus(part);
    const bestP = getBestPrice(part);
    const isAtBest = part.currentPrice <= bestP + 2;
    const sourceLabel = formatSource(part.source);

    let cardClass = "part-card";
    if (status === "triggered") cardClass += " part-card--sale";
    if (status === "rising") cardClass += " part-card--rising";

    const deltaClass =
      delta < -1 ? "delta--down" : delta > 1 ? "delta--up" : "delta--flat";
    const deltaText =
      delta < -1 ? fmtDelta(delta) : delta > 1 ? fmtDelta(delta) : "Stable";

    let tags = "";
    if (status === "triggered")
      tags += '<span class="tag tag--sale">ON SALE</span>';
    if (delta > 5) tags += '<span class="tag tag--rising">RISING</span>';
    if (isAtBest) tags += '<span class="tag tag--best">BEST PRICE</span>';
    if (part.source === "fallback" || part.source === "seed")
      tags +=
        '<span class="tag" style="background:var(--yellow-bg);color:var(--yellow)">ESTIMATED</span>';

    grid.innerHTML += `
      <div class="${cardClass}" data-part="${part.id}">
        <span class="part-card__type">${part.type}</span>
        <span class="part-card__name">${part.name}</span>
        <span class="part-card__retailer">${part.retailer} · <em>${sourceLabel}</em></span>
        <div class="part-card__price-row">
          <span class="part-card__price">${fmt(part.currentPrice)}</span>
          <span class="part-card__delta ${deltaClass}">${deltaText}</span>
        </div>
        <div class="part-card__tags">${tags}</div>
        <canvas class="part-card__spark" id="spark-${part.id}"></canvas>
      </div>
    `;
  });

  // Sparklines
  PARTS.forEach((part) => renderSparkline(part));

  // Total chart
  renderTotalChart();
}

// ────────────────────────────────────────────────────
// SPARKLINE CHARTS
// ────────────────────────────────────────────────────
function renderSparkline(part) {
  const canvas = document.getElementById(`spark-${part.id}`);
  if (!canvas) return;
  if (sparkCharts[part.id]) sparkCharts[part.id].destroy();

  const hist = part.history || [];
  const last30 = hist.slice(-30);
  if (last30.length < 2) return;

  const prices = last30.map((h) => h.price);
  const labels = last30.map((h) => h.date);
  const delta = getDelta(part);

  const cs = getComputedStyle(document.documentElement);
  const lineColor =
    delta < -1
      ? cs.getPropertyValue("--green").trim()
      : delta > 1
      ? cs.getPropertyValue("--red").trim()
      : cs.getPropertyValue("--text-muted").trim();

  sparkCharts[part.id] = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data: prices,
          borderColor: lineColor,
          borderWidth: 2,
          fill: { target: "origin", above: lineColor + "18" },
          pointRadius: 0,
          tension: 0.35,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
      interaction: { mode: "none" },
      animation: { duration: 600 },
    },
  });
}

// ────────────────────────────────────────────────────
// TOTAL CHART
// ────────────────────────────────────────────────────
function renderTotalChart() {
  const canvas = document.getElementById("totalChart");
  if (!canvas) return;
  if (totalChartInst) totalChartInst.destroy();

  // Build total cost per day from all parts' histories
  const allDates = new Set();
  PARTS.forEach((p) => (p.history || []).forEach((h) => allDates.add(h.date)));
  const sortedDates = [...allDates].sort();

  if (sortedDates.length < 2) {
    totalChartInst = null;
    return;
  }

  const totals = sortedDates.map((date) => {
    let dayTotal = 0;
    PARTS.forEach((p) => {
      const hist = p.history || [];
      const entry = hist.find((h) => h.date === date);
      if (entry) {
        dayTotal += entry.price;
      } else {
        const prev = hist.filter((h) => h.date <= date);
        dayTotal += prev.length
          ? prev[prev.length - 1].price
          : p.currentPrice;
      }
    });
    return Math.round(dayTotal);
  });

  const cs = getComputedStyle(document.documentElement);
  const accent = cs.getPropertyValue("--accent").trim();
  const textDim = cs.getPropertyValue("--text-dim").trim();
  const border = cs.getPropertyValue("--border").trim();

  totalChartInst = new Chart(canvas, {
    type: "line",
    data: {
      labels: sortedDates,
      datasets: [
        {
          label: "Total Build Cost (AUD)",
          data: totals,
          borderColor: accent,
          borderWidth: 2.5,
          backgroundColor: accent + "15",
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: accent,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cs.getPropertyValue("--bg-card").trim(),
          titleColor: cs.getPropertyValue("--text").trim(),
          bodyColor: textDim,
          borderColor: border,
          borderWidth: 1,
          padding: 12,
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            title: (items) => items[0].label,
            label: (item) => "Total: $" + item.raw.toLocaleString(),
          },
        },
      },
      scales: {
        x: {
          ticks: { color: textDim, maxTicksLimit: 10, font: { size: 11 } },
          grid: { color: border + "44" },
        },
        y: {
          ticks: {
            color: textDim,
            font: { size: 11 },
            callback: (v) => "$" + v.toLocaleString(),
          },
          grid: { color: border + "44" },
        },
      },
      interaction: { intersect: false, mode: "index" },
      animation: { duration: 800 },
    },
  });
}

// ────────────────────────────────────────────────────
// RENDERING — PARTS LIST VIEW
// ────────────────────────────────────────────────────
function renderPartsList() {
  const list = document.getElementById("partsList");
  list.innerHTML = "";

  // Header
  list.innerHTML += `
    <div class="part-row" style="background:transparent;border:none;box-shadow:none;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);">
      <span>Type</span>
      <span>Component</span>
      <span style="text-align:right">Current</span>
      <span style="text-align:right">Best Seen</span>
      <span style="text-align:right">7-Day</span>
    </div>
  `;

  PARTS.forEach((part) => {
    const delta = getDelta(part);
    const bestP = getBestPrice(part);
    const deltaClass = delta < -1 ? "positive" : delta > 1 ? "negative" : "";
    const sourceLabel = formatSource(part.source);
    const stockBadge =
      part.in_stock === false
        ? ' <span style="color:var(--red)">Out of stock</span>'
        : "";

    list.innerHTML += `
      <div class="part-row" data-part="${part.id}">
        <span class="part-row__type">${part.type}</span>
        <span class="part-row__name">${part.name}<br><small style="color:var(--text-dim);font-weight:400">${part.retailer} · ${sourceLabel}${stockBadge}</small></span>
        <span class="part-row__price">${fmt(part.currentPrice)}</span>
        <span class="part-row__best">${fmt(Math.round(bestP))}</span>
        <span class="part-row__delta ${deltaClass}">${fmtDelta(delta)}</span>
      </div>
    `;
  });

  // Total row
  const total = totalCost();
  list.innerHTML += `
    <div class="part-row" style="border-color:var(--accent);margin-top:8px;">
      <span class="part-row__type" style="color:var(--accent)">TOTAL</span>
      <span class="part-row__name" style="font-weight:800">Complete Build</span>
      <span class="part-row__price" style="font-size:1.3rem;color:var(--accent)">${fmt(total)}</span>
      <span class="part-row__best">${fmt(Math.round(bestTotalEver()))}</span>
      <span class="part-row__delta">${fmtDelta(totalCost() - totalWeekAgo())}</span>
    </div>
  `;
}

// ────────────────────────────────────────────────────
// RENDERING — ALERTS VIEW
// ────────────────────────────────────────────────────
function renderAlerts() {
  const list = document.getElementById("alertsList");
  list.innerHTML = "";

  PARTS.forEach((part) => {
    const target = alerts[part.id] || part.alertTarget || 0;
    const status = getAlertStatus(part);
    const statusClass =
      status === "triggered"
        ? "status--triggered"
        : status === "rising"
        ? "status--rising"
        : "status--watching";
    const statusLabel =
      status === "triggered"
        ? "Below Target ✓"
        : status === "rising"
        ? "Price Rising ▲"
        : "Watching";

    list.innerHTML += `
      <div class="alert-card" data-part="${part.id}">
        <div class="alert-card__info">
          <div class="alert-card__name">${part.name}</div>
          <div class="alert-card__meta">${part.type} · Current: ${fmt(part.currentPrice)}</div>
        </div>
        <span class="alert-card__status ${statusClass}">${statusLabel}</span>
        <div class="alert-card__target">
          <div class="alert-card__target-label">Target</div>
          <div class="alert-card__target-value">${fmt(target)}</div>
        </div>
        <div class="alert-card__actions">
          <button class="alert-card__btn" onclick="editAlert('${part.id}')">Edit</button>
        </div>
      </div>
    `;
  });
}

// ────────────────────────────────────────────────────
// ALERT EDITING
// ────────────────────────────────────────────────────
function editAlert(partId) {
  const part = PARTS.find((p) => p.id === partId);
  if (!part) return;
  const target = alerts[partId] || part.alertTarget || 0;

  const overlay = document.getElementById("modalOverlay");
  const content = document.getElementById("modalContent");

  content.innerHTML = `
    <h3 class="modal__title">Edit Alert — ${part.name}</h3>
    <p style="color:var(--text-dim);font-size:.88rem;margin-bottom:8px">
      Current price: <strong>${fmt(part.currentPrice)}</strong>
    </p>
    <label class="modal__label">Target Price (AUD)</label>
    <input class="modal__input" type="number" id="alertInput" value="${target}" min="0" step="5" />
    <div class="modal__actions">
      <button class="btn btn--ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn--primary" onclick="saveAlertEdit('${partId}')">Save</button>
    </div>
  `;

  overlay.classList.remove("hidden");
}

async function saveAlertEdit(partId) {
  const val = parseInt(document.getElementById("alertInput").value, 10);
  if (isNaN(val) || val < 0) return;

  alerts[partId] = val;
  await saveAlertToServer(partId, val);

  closeModal();
  renderAlerts();
  renderDashboard();
}

function closeModal() {
  document.getElementById("modalOverlay").classList.add("hidden");
}

// ────────────────────────────────────────────────────
// TOAST NOTIFICATIONS
// ────────────────────────────────────────────────────
function showToast(title, body, type = "") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = "toast" + (type ? ` toast--${type}` : "");
  toast.innerHTML = `
    <div class="toast__title">${title}</div>
    <div class="toast__body">${body}</div>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(40px)";
    toast.style.transition = ".3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 5000);
}

// ────────────────────────────────────────────────────
// NAVIGATION
// ────────────────────────────────────────────────────
function renderCurrentView() {
  if (currentView === "dashboard") renderDashboard();
  else if (currentView === "parts") renderPartsList();
  else if (currentView === "alerts") renderAlerts();
}

function switchView(view) {
  currentView = view;

  document.querySelectorAll(".nav__btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });

  document.getElementById("viewDashboard").classList.toggle("hidden", view !== "dashboard");
  document.getElementById("viewParts").classList.toggle("hidden", view !== "parts");
  document.getElementById("viewAlerts").classList.toggle("hidden", view !== "alerts");

  renderCurrentView();
}

// ────────────────────────────────────────────────────
// THEME TOGGLE
// ────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("pc-stocks-theme");
  if (saved === "light") document.body.classList.add("light");
}

function toggleTheme() {
  document.body.classList.toggle("light");
  const isLight = document.body.classList.contains("light");
  localStorage.setItem("pc-stocks-theme", isLight ? "light" : "dark");
  if (currentView === "dashboard") renderDashboard();
}

// ────────────────────────────────────────────────────
// POLLING — Refresh data periodically
// ────────────────────────────────────────────────────
async function pollPrices() {
  const ok = await fetchPrices();
  if (ok) {
    PARTS.forEach((part) => {
      const target = alerts[part.id] || part.alertTarget;
      if (target && part.currentPrice <= target) {
        showToast(
          `${part.name} — Below Target!`,
          `Currently ${fmt(part.currentPrice)} (target: ${fmt(target)})`,
          "sale"
        );
      }
    });
    renderCurrentView();
  }
}

// ────────────────────────────────────────────────────
// INIT
// ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();

  // Nav buttons
  document.querySelectorAll(".nav__btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // Theme toggle
  document.getElementById("themeToggle").addEventListener("click", toggleTheme);

  // Close modal on overlay click
  document.getElementById("modalOverlay").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeModal();
  });

  // Scrape button
  const scrapeBtn = document.getElementById("scrapeBtn");
  if (scrapeBtn) scrapeBtn.addEventListener("click", triggerScrape);

  // Initial data load
  const ok = await fetchPrices();
  if (ok) {
    renderDashboard();
    showToast("Connected", `Tracking ${PARTS.length} components with real AU prices`, "sale");
  } else {
    showToast(
      "Offline Mode",
      "Could not reach the server. Run: python3 server.py",
      "warn"
    );
  }

  // Poll for updates every minute
  setInterval(pollPrices, REFRESH_INTERVAL);
});
