"""
PC STOCKS — API Server
Flask app that serves the frontend + exposes price data via REST API.
Background job scrapes prices every 6 hours.
"""

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

from scraper import scrape_all, PART_SCRAPE_CONFIG

# ─── Config ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "price_history.json"

LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("server")

# ─── Flask app ──────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
CORS(app)

# ─── Price history storage ──────────────────────────────────────────────────


def load_history() -> dict:
    """Load price history from JSON file."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.error("Failed to load history: %s", e)
    return {"parts": {}, "scrapes": []}


def save_history(data: dict):
    """Save price history to JSON file."""
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        log.error("Failed to save history: %s", e)


def seed_history():
    """
    Create initial history file from fallback prices if none exists.
    This gives the frontend something to show before the first real scrape.
    """
    if HISTORY_FILE.exists():
        return

    log.info("Seeding initial price history...")
    history = {"parts": {}, "scrapes": []}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for part in PART_SCRAPE_CONFIG:
        history["parts"][part["id"]] = {
            "id": part["id"],
            "type": part["type"],
            "name": part["name"],
            "spec": part["spec"],
            "currentPrice": part["fallback_price"],
            "retailer": "Estimated",
            "source": "seed",
            "in_stock": True,
            "stock_status": "unknown",
            "history": [
                {"date": today, "price": part["fallback_price"]}
            ],
            "alertTarget": round(part["fallback_price"] * 0.92),  # 8% below
        }

    history["scrapes"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "seeded",
        "count": len(PART_SCRAPE_CONFIG),
    })

    save_history(history)
    log.info("Seeded history for %d parts.", len(PART_SCRAPE_CONFIG))


def run_scrape():
    """Execute a full scrape and merge results into history."""
    log.info("━━ Starting price scrape ━━")
    history = load_history()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        results = scrape_all()
    except Exception as e:
        log.error("Scrape failed: %s", e)
        history["scrapes"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "error": str(e),
        })
        save_history(history)
        return

    updated = 0
    for result in results:
        pid = result["id"]

        if pid not in history["parts"]:
            # New part — initialise
            history["parts"][pid] = {
                "id": pid,
                "type": result["type"],
                "name": result["name"],
                "spec": result["spec"],
                "currentPrice": result["price"],
                "retailer": result["retailer"],
                "source": result["source"],
                "in_stock": result["in_stock"],
                "stock_status": result.get("stock_status", "unknown"),
                "history": [],
                "alertTarget": round(result["price"] * 0.92),
            }

        part_data = history["parts"][pid]

        # Always sync part metadata so config swaps (e.g. different model)
        # propagate without requiring a manual history reset.
        part_data["type"] = result["type"]
        part_data["name"] = result["name"]
        part_data["spec"] = result["spec"]

        # Only record real scraped prices (not fallback)
        if result["source"] != "fallback":
            part_data["currentPrice"] = result["price"]
            part_data["retailer"] = result["retailer"]
            part_data["source"] = result["source"]
            part_data["in_stock"] = result["in_stock"]
            part_data["stock_status"] = result.get("stock_status", "unknown")
            updated += 1

        # Append to history (one entry per day)
        hist = part_data["history"]
        if hist and hist[-1]["date"] == today:
            hist[-1]["price"] = part_data["currentPrice"]
        else:
            hist.append({"date": today, "price": part_data["currentPrice"]})

        # Keep last 365 days max
        if len(hist) > 365:
            part_data["history"] = hist[-365:]

    history["scrapes"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "updated": updated,
        "total": len(results),
    })

    save_history(history)
    log.info("━━ Scrape complete: %d/%d parts updated ━━", updated, len(results))


# ─── API routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(BASE_DIR), filename)


@app.route("/api/prices")
def api_prices():
    """Return all parts with current prices and history."""
    history = load_history()
    parts = list(history.get("parts", {}).values())
    for part in parts:
        part.setdefault(
            "stock_status",
            "in_stock" if part.get("in_stock", True) else "out_of_stock",
        )
    total = sum(p.get("currentPrice", 0) for p in parts)
    return jsonify({
        "parts": parts,
        "totalCost": round(total, 2),
        "lastScrape": history.get("scrapes", [{}])[-1] if history.get("scrapes") else None,
    })


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger a manual price scrape."""
    run_scrape()
    history = load_history()
    last = history.get("scrapes", [{}])[-1] if history.get("scrapes") else {}
    return jsonify({"status": "ok", "scrape": last})


@app.route("/api/alerts", methods=["GET"])
def api_get_alerts():
    """Return alert targets for all parts."""
    history = load_history()
    alerts = {}
    for pid, part in history.get("parts", {}).items():
        alerts[pid] = part.get("alertTarget", 0)
    return jsonify(alerts)


@app.route("/api/alerts", methods=["POST"])
def api_set_alert():
    """Set an alert target: {"partId": "cpu", "target": 780}"""
    data = request.get_json()
    if not data or "partId" not in data or "target" not in data:
        return jsonify({"error": "partId and target required"}), 400

    history = load_history()
    pid = data["partId"]
    if pid in history.get("parts", {}):
        history["parts"][pid]["alertTarget"] = int(data["target"])
        save_history(history)
        return jsonify({"status": "ok", "partId": pid, "target": int(data["target"])})
    return jsonify({"error": "part not found"}), 404


@app.route("/api/status")
def api_status():
    """Health check and last scrape info."""
    history = load_history()
    scrapes = history.get("scrapes", [])
    return jsonify({
        "status": "running",
        "parts_tracked": len(history.get("parts", {})),
        "total_scrapes": len(scrapes),
        "last_scrape": scrapes[-1] if scrapes else None,
    })


# ─── Background scheduler ──────────────────────────────────────────────────

scheduler = BackgroundScheduler()


def start_scheduler():
    """Start the background scraping scheduler."""
    # Scrape every 6 hours
    scheduler.add_job(run_scrape, "interval", hours=6, id="price_scrape")
    scheduler.start()
    log.info("Background scheduler started (scrapes every 6 hours).")


# ─── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    seed_history()

    # Run initial scrape on startup
    log.info("Running initial price scrape...")
    run_scrape()

    # Start scheduler for periodic scrapes
    start_scheduler()

    log.info("Server starting on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
