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
SL_BUFFER_ATR_MULT = 0.1
ATR_PERIOD = 14
MIN_RISK = 0.05
RR_TARGET = 1.0


def fetch_candles():
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }
    r = requests.get(url, params=params, timeout=30)
    data = r.json()
    if "values" not in data:
        raise RuntimeError(f"Twelve Data error: {data}")
    values = list(reversed(data["values"]))

    candles = []
    for v in values:
        candles.append({
            "dt": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        })

    now = datetime.now(timezone.utc)
    last_dt = datetime.strptime(candles[-1]["dt"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if (now - last_dt).total_seconds() < 5 * 60:
        candles = candles[:-1]

    return candles


def compute_atr(candles, period=ATR_PERIOD):
    trs = [None]
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = [None] * len(candles)
    for i in range(period, len(candles)):
        window = [t for t in trs[i-period+1:i+1] if t is not None]
        if len(window) == period:
            atr[i] = sum(window) / period
    return atr


def find_swings(candles, left=SWING_LEFT, right=SWING_RIGHT):
    n = len(candles)
    h = [c["high"] for c in candles]
    l = [c["low"] for c in candles]
    swing_high = [False] * n
    swing_low = [False] * n
    for i in range(left, n - right):
        window_h = h[i-left:i+right+1]
        window_l = l[i-left:i+right+1]
        if h[i] == max(window_h) and h[i] > max(h[i-left:i]) and h[i] > max(h[i+1:i+right+1]):
            swing_high[i] = True
        if l[i] == min(window_l) and l[i] < min(l[i-left:i]) and l[i] < min(l[i+1:i+right+1]):
            swing_low[i] = True
    return swing_high, swing_low


def find_latest_setup(candles, used_until_entry_time=None):
    """
    Scans the full candle batch for the ICT sweep -> MSS -> OB -> entry
    sequence, same logic as the backtest. Returns the most recent entry
    found (if its entry_time is newer than used_until_entry_time).
    """
    n = len(candles)
    h = [c["high"] for c in candles]
    l = [c["low"] for c in candles]
    o = [c["open"] for c in candles]
    c_ = [c["close"] for c in candles]
    dt = [c["dt"] for c in candles]
    atr = compute_atr(candles)

    sh, sl_arr = find_swings(candles)
    sh_idx = [i for i, v in enumerate(sh) if v]
    sl_idx = [i for i, v in enumerate(sl_arr) if v]

    latest_setup = None
    i = 20
    sh_ptr, sl_ptr = 0, 0

    while i < n - 3:
        while sh_ptr < len(sh_idx) and sh_idx[sh_ptr] < i:
            sh_ptr += 1
        while sl_ptr < len(sl_idx) and sl_idx[sl_ptr] < i:
            sl_ptr += 1

        direction = None
        sweep_extreme = None
        mss_idx = None
        ob_idx = None

        if sl_ptr >= 1 and sh_ptr >= 1:
            recent_sl = sl_idx[sl_ptr-1]
            recent_sl_price = l[recent_sl]
            if l[i] < recent_sl_price and c_[i] > recent_sl_price and recent_sl < i:
                sweep_extreme = l[i]
                recent_sh_price = h[sh_idx[sh_ptr-1]]
                for j in range(i+1, min(i+1+MSS_WAIT, n)):
                    if c_[j] > recent_sh_price:
                        mss_idx = j
                        break
                if mss_idx is not None:
                    for k in range(mss_idx-1, i-1, -1):
                        if c_[k] < o[k]:
                            ob_idx = k
                            break
                    if ob_idx is not None:
                        direction = "long"

        if direction is None and sl_ptr >= 1 and sh_ptr >= 1:
            recent_sh = sh_idx[sh_ptr-1]
            recent_sh_price = h[recent_sh]
            if h[i] > recent_sh_price and c_[i] < recent_sh_price and recent_sh < i:
                sweep_extreme = h[i]
                recent_sl_price = l[sl_idx[sl_ptr-1]]
                for j in range(i+1, min(i+1+MSS_WAIT, n)):
                    if c_[j] < recent_sl_price:
                        mss_idx = j
                        break
                if mss_idx is not None:
                    for k in range(mss_idx-1, i-1, -1):
                        if c_[k] > o[k]:
                            ob_idx = k
                            break
                    if ob_idx is not None:
                        direction = "short"

        if direction is None:
            i += 1; continue

        ob_high, ob_low = h[ob_idx], l[ob_idx]
        buffer = SL_BUFFER_ATR_MULT * atr[i] if atr[i] is not None else 0.0

        entry_idx = -1
        j_end = min(mss_idx+1+ENTRY_WAIT, n)
        for j in range(mss_idx+1, j_end):
            if direction == "long" and l[j] <= ob_high:
                entry_idx = j; break
            if direction == "short" and h[j] >= ob_low:
                entry_idx = j; break

        if entry_idx == -1:
            i = mss_idx + 1; continue

        entry_price = c_[entry_idx]
        sl = sweep_extreme - buffer if direction == "long" else sweep_extreme + buffer
        risk = abs(entry_price - sl)
        if risk < MIN_RISK:
            i = entry_idx + 1; continue

        target = entry_price + RR_TARGET*risk if direction == "long" else entry_price - RR_TARGET*risk

        if used_until_entry_time is None or dt[entry_idx] > used_until_entry_time:
            latest_setup = {
                "entry_time": dt[entry_idx],
                "direction": direction,
                "entry": round(entry_price, 2),
                "sl": round(sl, 2),
                "target": round(target, 2),
                "risk": round(risk, 2),
            }
        i = entry_idx + 1

    return latest_setup


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"open_trade": None, "last_alerted_entry_time": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(",")]
    for chat_id in chat_ids:
        requests.post(url, data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=15)


def monitor_open_trade(state, candles):
    trade = state["open_trade"]
    direction = trade["direction"]
    sl = trade["sl"]
    target = trade["target"]
    entry_time = trade["entry_time"]

    relevant = [c for c in candles if c["dt"] > entry_time]
    for c in relevant:
        if direction == "long":
            if c["low"] <= sl:
                send_telegram(
                    f"*ICT Sweep Bot — STOPPED OUT* ❌\nXAU/USD LONG hit stop `{sl}`.\nFull loss on this trade."
                )
                state["open_trade"] = None
                return state
            if c["high"] >= target:
                send_telegram(
                    f"*ICT Sweep Bot — TARGET HIT* ✅\nXAU/USD LONG hit target `{target}`.\n+1R on this trade."
                )
                state["open_trade"] = None
                return state
        else:
            if c["high"] >= sl:
                send_telegram(
                    f"*ICT Sweep Bot — STOPPED OUT* ❌\nXAU/USD SHORT hit stop `{sl}`.\nFull loss on this trade."
                )
                state["open_trade"] = None
                return state
            if c["low"] <= target:
                send_telegram(
                    f"*ICT Sweep Bot — TARGET HIT* ✅\nXAU/USD SHORT hit target `{target}`.\n+1R on this trade."
                )
                state["open_trade"] = None
                return state
    return state


def main():
    candles = fetch_candles()
    state = load_state()

    if state["open_trade"] is not None:
        state = monitor_open_trade(state, candles)
        save_state(state)
        if state["open_trade"] is not None:
            return  # still open, don't look for new entries

    setup = find_latest_setup(candles, used_until_entry_time=state.get("last_alerted_entry_time"))
    if setup is None:
        return

    state["last_alerted_entry_time"] = setup["entry_time"]
    state["open_trade"] = {
        "entry_time": setup["entry_time"],
        "direction": setup["direction"],
        "entry": setup["entry"],
        "sl": setup["sl"],
        "target": setup["target"],
    }
    save_state(state)

    send_telegram(
        f"*ICT Sweep Bot — NEW ENTRY* 🎯\n"
        f"XAU/USD {setup['direction'].upper()}\n"
        f"Entry: `{setup['entry']}`\n"
        f"Stop-loss: `{setup['sl']}`\n"
        f"Target (1:1): `{setup['target']}`\n"
        f"Risk: `{setup['risk']}`\n"
        f"Time: {setup['entry_time']} UTC"
    )


if __name__ == "__main__":
    main()
