# NeeDoh Watch UAE

Real-time stock monitoring system for NeeDoh fidget toys across UAE retailers.

Tracks **15 NeeDoh products** across **Amazon.ae**, **Noon**, and **Virgin Megastore UAE** with online restock alerts, offline community sightings, and confidence-scored availability signals.

## Quick Start (Web App)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Playwright browser (for Noon + Virgin scraping)
python -m playwright install chromium

# 3. Start the web dashboard
python app.py

# 4. Open http://localhost:5000 in your browser!
```

That's it — the dashboard opens with all 15 products, live stock checking, alerts, sighting reports, and a wishlist. Click "Check Now" to run your first scan.

## Quick Start (CLI)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure notifications (optional)
cp .env.example .env
# Edit .env with your email/WhatsApp credentials

# 3. Seed database and run one check
python main.py --once

# 4. Start interactive CLI
python main.py --cli

# 5. Start continuous monitoring
python main.py
```

## CLI Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/track <product> [under <price>]` | Subscribe to alerts | `/track nice cube under 60` |
| `/stop <product>` | Unsubscribe | `/stop nice cube` |
| `/where <product>` | Find availability | `/where nice cube` |
| `/seen <product> <store> [mall]` | Report a sighting | `/seen nice cube virgin dubai mall` |
| `/wishlist` | View subscriptions | `/wishlist` |
| `/status` | All product statuses | `/status` |
| `/check [product]` | Immediate check | `/check snowball crunch` |
| `/dashboard` | Full dashboard | `/dashboard` |
| `/products` | List products | `/products` |
| `/stores` | List stores | `/stores` |

## Architecture

```
needoh_watch/
├── main.py              # Entry point & scheduler
├── cli.py               # Interactive CLI with all commands
├── data/
│   ├── database.py      # SQLite database layer
│   └── seed.py          # Product/store seed data
├── scrapers/
│   ├── base.py          # Base scraper class
│   ├── amazon_ae.py     # Amazon.ae scraper
│   ├── noon_uae.py      # Noon UAE scraper (API + HTML)
│   └── virgin_uae.py    # Virgin Megastore scraper (with store check)
├── engines/
│   ├── checker.py       # Stock checking orchestrator
│   ├── normalizer.py    # Status normalization + AI layer
│   ├── alert_engine.py  # Alert triggering logic
│   └── offline_engine.py# Sightings & confidence scoring
├── notifications/
│   └── notifier.py      # Email + WhatsApp notifications
├── .env.example         # Configuration template
└── requirements.txt     # Python dependencies
```

## How It Works

### Engine 1: Online Restock Watcher
- Checks product pages on Amazon.ae (every 5min), Noon (every 5min), and Virgin (every 15min)
- Detects stock changes (IN_STOCK, LOW_STOCK, OUT_OF_STOCK)
- Sends alerts on restock events and price drops

### Engine 2: Offline Availability Signals
- Reads Virgin's in-store availability checker
- Accepts community sightings with location/photo
- Confidence scoring: store page (+50), fresh sighting (+25), confirmations (+15 each), photo (+10)

### Alert Types
- **Restock**: OUT_OF_STOCK → IN_STOCK
- **Price Drop**: 10%+ price decrease
- **Price Threshold**: Below your target price
- **Store Available**: Virgin shows in-store availability
- **Sightings**: Multiple reports at same location

## Notifications

### Email (Gmail)
Set in `.env`:
```
EMAIL_ENABLED=true
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SENDER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
EMAIL_RECIPIENTS=your-email@gmail.com
```

### WhatsApp (via Twilio)
```
WHATSAPP_ENABLED=true
TWILIO_ACCOUNT_SID=your-sid
TWILIO_AUTH_TOKEN=your-token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_RECIPIENTS=whatsapp:+971xxxxxxxxx
```

### AI Summaries (Optional)
Add your OpenAI key for richer alert messages:
```
OPENAI_API_KEY=sk-your-key
```
The system works perfectly without AI — it uses template-based messages by default.

## Tracked Products

Nice Cube, Swirl Nice Cube, Snowball Crunch, Dohnuts, Teenie Needoh, Gummy Bear, Fuzz Ball, Ramen Noodlies, Cool Cats, Dig It Pig, Mac N Squeeze, Diddy Doh, Groovy Fruit, NeeDoh Blob, Super Needoh

## Confidence Scoring

| Score | Label | Meaning |
|-------|-------|---------|
| 80+ | High | Store page confirms + multiple reports |
| 50-79 | Medium | Recent sighting or store signal |
| <50 | Low | Single unconfirmed report |

## Deploy to the Web (Free)

### Option A: Render.com (Recommended — Free)
1. Push this folder to a GitHub repo
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects the `render.yaml` — just click Deploy
5. You'll get a URL like `needoh-watch.onrender.com`

### Option B: PythonAnywhere (Free)
1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Upload the `needoh_watch` folder
3. Create a new Web App → Flask → Python 3.10
4. Set the source code directory and WSGI file to point to `app.py`
5. You'll get `yourusername.pythonanywhere.com`

### Option C: Railway (Free tier)
1. Push to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Railway reads the `Procfile` automatically

### Custom Domain (Optional)
Buy a domain like `needohwatch.com` (~$10/year from Namecheap or GoDaddy), then point it at whichever host you chose above. Each host has instructions for custom domains in their docs.
