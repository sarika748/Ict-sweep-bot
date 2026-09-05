"""
ICT Sweep + Market Structure Shift + Order Block Bot -- XAU/USD 5-min
Strategy: liquidity sweep of a recent swing low/high -> market structure
shift (close beyond the opposite swing point) -> order block (last
opposite-colored candle before the impulsive move) -> entry on retracement
back into the order block -> fixed 1:1 R:R.

Backtest reference (5-min, no higher-timeframe bias, 6.5yr XAU/USD):
  7,346 trades, 53.57% win rate, +524.41R total at 1:1.

Sends Telegram alerts to every chat ID listed in TELEGRAM_CHAT_ID
(comma-separated -- add both your phones' chat IDs there).

Requires environment variables (GitHub Secrets):
  TWELVE_DATA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import json
import requests
from datetime import datetime, timezone

TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SYMBOL = "XAU/USD"
INTERVAL = "5min"
OUTPUT_SIZE = 300
STATE_FILE = "ict_sweep_state.json"

SWING_LEFT = 2
SWING_RIGHT = 2
MSS_WAIT = 50
ENTRY_WAIT = 150
