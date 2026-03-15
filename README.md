# WARNING
Complete AI generated slop. I'm too sleep deprived and tired to actually read, understand or care about any of this.

# 🇺🇸 US Visa Appointment Scheduler

Automatically monitors the US visa appointment system ([ais.usvisa-info.com](https://ais.usvisa-info.com)) for earlier available dates and sends **Telegram notifications** when a better slot is found. Optionally auto-reschedules.

## Features

- 🔍 **Monitors** available visa appointment dates at your chosen consulate
- 📱 **Telegram notifications** when an earlier date is found
- 🔄 **Auto-reschedule** (optional) — automatically books the earlier slot
- 🕐 **Configurable polling interval** with jitter to avoid detection
- 🌍 **Multi-consulate** support — monitor multiple locations simultaneously
- 🛡️ **Anti-detection** — randomized delays, realistic headers, session management
- 🐳 **Docker support** for easy deployment
- 📊 **Logging** with rotation for long-running monitoring

## Prerequisites

- Python 3.10+
- A valid account on [ais.usvisa-info.com](https://ais.usvisa-info.com) with an existing appointment
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID (from [@userinfobot](https://t.me/userinfobot))

## Quick Start

### 1. Clone & Install

```bash
git clone <repo-url>
cd us-visa-scheduler

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# US Visa System Credentials
USVISA_EMAIL=your-email@example.com
USVISA_PASSWORD=your-password
SCHEDULE_ID=12345678

# Consulate Configuration
FACILITY_IDS=89,94,95   # Comma-separated, see facility_ids.md
COUNTRY_CODE=en-ca      # Country code in URL (e.g., en-ca, en-in, en-gb)

# Current Appointment Date (YYYY-MM-DD)
CURRENT_APPOINTMENT_DATE=2026-09-15

# Telegram Configuration
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=123456789

# Scheduler Settings
CHECK_INTERVAL_MINUTES=10       # How often to check (default: 10)
CHECK_INTERVAL_JITTER_MINUTES=5 # Random jitter added (default: 5)
AUTO_RESCHEDULE=false           # Auto-book earlier date (default: false)
```

### 3. Run

```bash
# Run the scheduler
python -m src.main

# Or with Docker
docker-compose up -d
```

## Setup Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** → `TELEGRAM_BOT_TOKEN`
4. Search for **@userinfobot** and send `/start`
5. Copy your **chat ID** → `TELEGRAM_CHAT_ID`
6. **Start a conversation** with your new bot (send `/start` to it)

## Facility IDs

See [facility_ids.md](facility_ids.md) for a list of common consulate facility IDs.

Common ones:
| Facility | ID |
|----------|-----|
| Calgary | 89 |
| Halifax | 90 |
| Montreal | 91 |
| Ottawa | 92 |
| Quebec City | 93 |
| Toronto | 94 |
| Vancouver | 95 |
| Mumbai | 5 |
| Chennai | 6 |
| Hyderabad | 7 |
| Kolkata | 8 |
| New Delhi | 9 |
| London | 18 |

## Architecture

```
src/
├── main.py              # Entry point & scheduler loop
├── config.py            # Configuration from environment
├── visa_client.py       # Browser automation for ais.usvisa-info.com
├── telegram_notifier.py # Telegram bot notifications
├── scheduler.py         # Scheduling logic & date comparison
└── utils.py             # Logging, retry helpers
```

## Docker Deployment

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## ⚠️ Disclaimer

This tool is for **personal use only**. Use responsibly and respect the terms of service of ais.usvisa-info.com. The authors are not responsible for any consequences of using this tool, including but not limited to account suspension.

## License

MIT
