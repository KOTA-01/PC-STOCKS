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
let buildSelections = {};

const BUILD_SELECTIONS_KEY = "pc-stocks-build-selections";

const BUILD_OPTIONS = {
  cpu: [
    { name: "AMD Ryzen 9 9950X", spec: "16-Core / 32-Thread", price: 897 },
    { name: "AMD Ryzen 9 9900X", spec: "12-Core / 24-Thread", price: 639 },
    { name: "AMD Ryzen 7 9700X", spec: "8-Core / 16-Thread", price: 469 },
  ],
  ram: [
    { name: "Corsair Vengeance 96 GB DDR5-6000 CL36 (CMK96GX5M2E6000Z36)", spec: "2 x 48 GB", price: 1099 },
    { name: "Team T-Force Delta RGB 64 GB DDR5-6000 CL38 (FF3D564G6000HC38JDC01)", spec: "2 x 32 GB", price: 889 },
  ],
  ssd1: [
    { name: "Samsung 990 Pro 2 TB NVMe", spec: "PCIe 4.0", price: 489 },
    { name: "Samsung 990 Pro 4 TB NVMe", spec: "PCIe 4.0", price: 779 },
  ],
  gpu: [
    { name: "PNY GeForce RTX 5060 ARGB OC Triple Fan 8 GB (VCG50608TFXXPB1-O)", spec: "Triple-fan OC", price: 489 },
    { name: "ASUS GeForce RTX 5060 TUF Gaming OC 8 GB", spec: "Triple-fan OC", price: 599 },
    { name: "PNY GeForce RTX 5070 OC 12 GB", spec: "12 GB GDDR7", price: 899 },
  ],
};

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

/**
 * Detect whether the current price qualifies as "on sale".
 * True when ANY of:
 *   1. Price dropped vs. the previous recorded price (by >$2)
 *   2. Current price is below the historical average by >5%
 *      (requires ≥3 history entries so we have real context)
 *   3. A user-set price alert has been triggered
 *   4. Current price equals all-time best AND there have been
 *      higher prices recorded (a genuine discount, not just stable)
 */
function isOnSale(part) {
  const h = part.history || [];
  const cur = part.currentPrice;

  // Alert-triggered counts as on sale
  if (getAlertStatus(part) === "triggered") return true;

  if (h.length < 2) return false;

  // Price dropped compared to the previous entry
  const prev = h[h.length - 2]?.price;
  if (prev && cur < prev - 2) return true;

  // Need ≥3 data points for average / best-ever checks
  if (h.length >= 3) {
    const best = getBestPrice(part);
    const max  = Math.max(...h.map((e) => e.price));
    const avg  = h.reduce((s, e) => s + e.price, 0) / h.length;

    // Below the historical average by >5 %
    if (cur < avg * 0.95) return true;

    // At the all-time best AND the highest recorded price was >3 % higher
    // (ensures there was a real price range, not just a flat line)
    if (cur <= best + 3 && max > best * 1.03) return true;
  }

  return false;
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
  if (!source) return "Unknown";
  // Known sources with custom labels
  const labels = {
    pcpartpicker: "PCPartPicker AU",
    pcpartpicker_au: "PCPartPicker AU",
    staticice: "StaticICE",
    fallback: "Estimated",
    seed: "Initial estimate",
    scorptec: "Scorptec",
    pc_case_gear: "PC Case Gear",
    centre_com: "Centre Com",
    umart: "Umart",
    amazon_au: "Amazon AU",
    computer_alliance: "Computer Alliance",
    msy: "MSY",
  };
  return labels[source] || source.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function loadBuildSelections() {
  try {
    const raw = localStorage.getItem(BUILD_SELECTIONS_KEY);
    buildSelections = raw ? JSON.parse(raw) : {};
  } catch {
    buildSelections = {};
  }
}

function saveBuildSelections() {
  localStorage.setItem(BUILD_SELECTIONS_KEY, JSON.stringify(buildSelections));
}

function getStockStatus(part) {
  if (part.stock_status) return part.stock_status;
  return part.in_stock === false ? "out_of_stock" : "unknown";
}

function stockTag(part) {
  const status = getStockStatus(part);
  if (status === "in_stock") {
    return '<span class="tag" style="background:var(--green-bg);color:var(--green)">IN STOCK</span>';
  }
  if (status === "out_of_stock") {
    return '<span class="tag" style="background:var(--red-bg);color:var(--red)">OUT OF STOCK</span>';
  }
  return '<span class="tag" style="background:var(--yellow-bg);color:var(--yellow)">STOCK UNCONFIRMED</span>';
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
  
  const gridHTML = PARTS.map((part) => {
    const delta = getDelta(part);
    const status = getAlertStatus(part);
    const bestP = getBestPrice(part);
    const isAtBest = part.currentPrice <= bestP + 2;
    const sourceLabel = formatSource(part.source);

    const onSale = isOnSale(part);

    let cardClass = "part-card";
    if (onSale) cardClass += " part-card--sale";
    else if (status === "rising") cardClass += " part-card--rising";

    const deltaClass =
      delta < -1 ? "delta--down" : delta > 1 ? "delta--up" : "delta--flat";
    const deltaText =
      delta < -1 ? fmtDelta(delta) : delta > 1 ? fmtDelta(delta) : "Stable";

    let tags = "";
    if (onSale)
      tags += '<span class="tag tag--sale">ON SALE</span>';
    if (delta > 5) tags += '<span class="tag tag--rising">RISING</span>';
    if (isAtBest) tags += '<span class="tag tag--best">BEST PRICE</span>';
    tags += stockTag(part);
    if (part.source === "fallback" || part.source === "seed")
      tags +=
        '<span class="tag" style="background:var(--yellow-bg);color:var(--yellow)">ESTIMATED</span>';

    return `
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
  }).join('');
  
  grid.innerHTML = gridHTML;

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

  // Header
  let listHTML = `
    <div class="part-row" style="background:transparent;border:none;box-shadow:none;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);">
      <span>Type</span>
      <span>Component</span>
      <span style="text-align:right">Current</span>
      <span style="text-align:right">Best Seen</span>
      <span style="text-align:right">7-Day</span>
    </div>
  `;

  listHTML += PARTS.map((part) => {
    const delta = getDelta(part);
    const bestP = getBestPrice(part);
    const deltaClass = delta < -1 ? "positive" : delta > 1 ? "negative" : "";
    const sourceLabel = formatSource(part.source);
    const onSale = isOnSale(part);
    const stockStatus = getStockStatus(part);
    const stockBadge =
      stockStatus === "in_stock"
        ? ' <span style="color:var(--green)">In stock</span>'
        : stockStatus === "out_of_stock"
        ? ' <span style="color:var(--red)">Out of stock</span>'
        : ' <span style="color:var(--yellow)">Stock unconfirmed</span>';
    const saleBadge = onSale
        ? ' <span class="tag tag--sale" style="font-size:.6rem;padding:1px 6px;margin-left:4px">ON SALE</span>'
        : "";

    return `
      <div class="part-row${onSale ? ' part-row--sale' : ''}" data-part="${part.id}">
        <span class="part-row__type">${part.type}</span>
        <span class="part-row__name">${part.name}<br><small style="color:var(--text-dim);font-weight:400">${part.retailer} · ${sourceLabel}${stockBadge}${saleBadge}</small></span>
        <span class="part-row__price">${fmt(part.currentPrice)}</span>
        <span class="part-row__best">${fmt(Math.round(bestP))}</span>
        <span class="part-row__delta ${deltaClass}">${fmtDelta(delta)}</span>
      </div>
    `;
  }).join('');

  // Total row
  const total = totalCost();
  listHTML += `
    <div class="part-row" style="border-color:var(--accent);margin-top:8px;">
      <span class="part-row__type" style="color:var(--accent)">TOTAL</span>
      <span class="part-row__name" style="font-weight:800">Complete Build</span>
      <span class="part-row__price" style="font-size:1.3rem;color:var(--accent)">${fmt(total)}</span>
      <span class="part-row__best">${fmt(Math.round(bestTotalEver()))}</span>
      <span class="part-row__delta">${fmtDelta(totalCost() - totalWeekAgo())}</span>
    </div>
  `;
  
  list.innerHTML = listHTML;
}

// ────────────────────────────────────────────────────
// RENDERING — ALERTS VIEW
// ────────────────────────────────────────────────────
function renderAlerts() {
  const list = document.getElementById("alertsList");

  const alertsHTML = PARTS.map((part) => {
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

    return `
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
  }).join('');
  
  list.innerHTML = alertsHTML;
}

function getOptionsForPart(part) {
  const base = BUILD_OPTIONS[part.id] ? [...BUILD_OPTIONS[part.id]] : [];
  if (!base.some((opt) => opt.name === part.name)) {
    base.unshift({
      name: part.name,
      spec: part.spec || part.type,
      price: part.currentPrice,
    });
  }
  return base;
}

function getSelectionForPart(part) {
  const options = getOptionsForPart(part);
  const selectedName = buildSelections[part.id];
  const selected = options.find((opt) => opt.name === selectedName);
  return selected || options[0];
}

function updateBuildSelection(partId, value) {
  buildSelections[partId] = value;
  saveBuildSelections();
  renderBuilder();
}

function resetBuildSelections() {
  buildSelections = {};
  saveBuildSelections();
  renderBuilder();
}

function renderBuilder() {
  const grid = document.getElementById("builderGrid");
  const summary = document.getElementById("builderSummary");
  if (!grid || !summary || PARTS.length === 0) return;

  grid.innerHTML = PARTS.map((part) => {
    const options = getOptionsForPart(part);
    const selected = getSelectionForPart(part);

    const optionsHTML = options.map((opt) => {
      const selectedAttr = opt.name === selected.name ? "selected" : "";
      return `<option value="${opt.name.replace(/"/g, "&quot;")}" ${selectedAttr}>${opt.name}</option>`;
    }).join("");

    return `
      <article class="builder-card">
        <div class="builder-card__type">${part.type}</div>
        <label class="builder-card__label">Select Part</label>
        <select class="builder-card__select" data-part-id="${part.id}">
          ${optionsHTML}
        </select>
        <div class="builder-card__meta">${selected.spec || ""}</div>
        <div class="builder-card__price">Est. ${fmt(selected.price ?? part.currentPrice)}</div>
      </article>
    `;
  }).join("");

  const selectedRows = PARTS.map((part) => {
    const selected = getSelectionForPart(part);
    return {
      type: part.type,
      name: selected.name,
      price: selected.price ?? part.currentPrice,
    };
  });

  const total = selectedRows.reduce((sum, row) => sum + row.price, 0);
  summary.innerHTML = `
    <h3 class="builder-summary__title">Selected Build Summary</h3>
    ${selectedRows.map((row) => `
      <div class="builder-summary__row">
        <span>${row.type}</span>
        <span>${fmt(row.price)}</span>
      </div>
    `).join("")}
    <div class="builder-summary__total">
      <span>Total</span>
      <span>${fmt(total)}</span>
    </div>
  `;

  grid.querySelectorAll(".builder-card__select").forEach((select) => {
    select.addEventListener("change", (e) => {
      const partId = e.target.dataset.partId;
      updateBuildSelection(partId, e.target.value);
    });
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
  else if (currentView === "builder") renderBuilder();
  else if (currentView === "alerts") renderAlerts();
}

function switchView(view) {
  currentView = view;

  document.querySelectorAll(".nav__btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });

  document.getElementById("viewDashboard").classList.toggle("hidden", view !== "dashboard");
  document.getElementById("viewParts").classList.toggle("hidden", view !== "parts");
  document.getElementById("viewBuilder").classList.toggle("hidden", view !== "builder");
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
  loadBuildSelections();

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

  const resetBuildBtn = document.getElementById("resetBuildBtn");
  if (resetBuildBtn) resetBuildBtn.addEventListener("click", resetBuildSelections);

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
