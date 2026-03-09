# PC STOCKS — Coding Rig Price Tracker

Live Australian price tracker for a custom developer workstation build.  
Scrapes real prices from **PCPartPicker AU** and **StaticICE** every 6 hours and logs history over time.

## The Build (Lian Li A3 Wood Edition)

| Component | Part | Live Price (AUD) |
|-----------|------|----------------:|
| CPU | AMD Ryzen 9 9950X (16c/32t) | ~$895 |
| Cooler | ARCTIC Liquid Freezer III Pro 360 | ~$169 |
| Motherboard | MSI MAG X870 Tomahawk WiFi | ~$499 |
| Memory | Corsair Vengeance 96 GB DDR5-6000 CL36 (2×48) | ~$999 |
| Storage | Samsung 990 Pro 2 TB NVMe | ~$329 |
| GPU | ASUS ProArt RTX 4060 OC 8 GB | ~$499 |
| Case | Lian Li DAN A3 Wood mATX | ~$129 |
| PSU | MSI MAG A850GL PCIE5 850W Gold | ~$139 |
| **Total** | | **~$3,658 AUD** |

*Prices update automatically — values above are approximate.*

## Features

- **Live price scraping** — pulls real AUD prices from PCPartPicker AU & StaticICE
- **Dashboard** — total build cost, weekly delta, best-price tracker, sparkline charts per part
- **Parts View** — detailed table with current price, source retailer, and 7-day change
- **Alerts** — set target prices per part; get toast notifications when prices drop or spike
- **Price history** — logs daily prices for up to 365 days, viewable as charts
- **Auto-scraping** — background job runs every 6 hours via APScheduler
- **Light / Dark mode** — warm wood-accent colour scheme
- **iPhone optimised** — bottom tab bar, safe areas, 44px touch targets, responsive layout
- **systemd service** — auto-starts on boot, restarts on crash

## Tech Stack

- **Frontend:** HTML / CSS / JS + Chart.js (CDN)
- **Backend:** Python 3, Flask, Flask-CORS
- **Scraping:** requests + BeautifulSoup4 (PCPartPicker AU, StaticICE AU)
- **Scheduling:** APScheduler (background, every 6 hours)
- **Storage:** JSON file (`data/price_history.json`)

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (serves frontend + API on port 5000)
python3 server.py

# Open in browser
open http://localhost:5000
```

### Access from other devices (phone, tablet, etc.)

The server binds to `0.0.0.0`, so any device on the same network can access it.  
Find your local IP and open it in a browser:

```bash
# Find your IP
hostname -I | awk '{print $1}'

# Then open on your phone:
# http://<YOUR_IP>:5000
```

If it doesn't connect, allow port 5000 through the firewall:

```bash
sudo ufw allow 5000/tcp
```

### Run as a systemd user service

```bash
# Copy the service file
mkdir -p ~/.config/systemd/user
cp pc-stocks.service ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now pc-stocks

# Enable linger so it runs when logged out
loginctl enable-linger $USER
```

### Useful commands

```bash
systemctl --user status pc-stocks     # check status
systemctl --user restart pc-stocks    # restart after code changes
journalctl --user -u pc-stocks -f     # tail live logs
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/prices` | Current prices + history for all parts |
| POST | `/api/scrape` | Trigger an immediate price scrape |
| GET | `/api/status` | Server status + last scrape info |
| GET/POST | `/api/alerts` | Get or set alert targets |

## Project Structure

```
PC-STOCKS/
├── index.html          # Main page
├── styles.css          # Design system (dark/light, responsive)
├── app.js              # Frontend logic, charts, alerts
├── server.py           # Flask API + background scheduler
├── scraper.py          # Price scraping (PCPartPicker + StaticICE)
├── requirements.txt    # Python dependencies
└── data/
    └── price_history.json  # Persistent price data
```