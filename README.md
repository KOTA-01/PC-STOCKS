# PC STOCKS — Jett's Coding Rig Price Tracker

A clean, modern price-tracking dashboard for a custom developer workstation build.

## The Build (Lian Li A3 Wood Edition)

| Component | Part | Est. Price (AUD) |
|-----------|------|----------------:|
| CPU | AMD Ryzen 9 9950X (16c/32t) | $825 |
| Cooler | ARCTIC Liquid Freezer III Pro 360 | $169 |
| Motherboard | MSI MAG X870 Tomahawk WiFi | $467 |
| Memory | Corsair Vengeance 96 GB DDR5-6000 CL36 (2×48) | $900 |
| Storage (OS) | Samsung 990 Pro 2 TB NVMe | $280 |
| Storage (Dev) | WD Black SN850X 2 TB NVMe | $260 |
| GPU | ASUS ProArt RTX 4060 OC 8 GB | $499 |
| Case | Lian Li DAN A3 Wood mATX | $145 |
| PSU | MSI MAG A850GL PCIE5 850W Gold | $139 |
| **Total** | | **~$3,684 AUD** |

## Features

- **Dashboard** — total build cost, weekly delta, best-price tracker, component breakdown with sparklines
- **Parts View** — detailed table with current / best / 7-day change for every component
- **Alerts** — set target prices per part; get toast notifications when prices drop below target or spike
- **Simulated live prices** — prices fluctuate every 15 seconds to demo the tracking
- **Light / Dark mode** — warm wood-accent colour scheme in both themes
- **Responsive** — works on desktop, tablet, and mobile

## Run Locally

```bash
python3 -m http.server 8765
# open http://localhost:8765
```

No build tools needed — pure HTML/CSS/JS with Chart.js via CDN.