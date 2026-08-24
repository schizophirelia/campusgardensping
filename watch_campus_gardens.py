#!/usr/bin/env python3
"""
Campus Gardens Heidelberg — apartment availability watcher.

Checks https://www.campus-gardens.de/en/rent for the per-house
"free: N" counters (House A/Asia, B/Australia, C/Europe, D/America)
and sends a Telegram notification the moment any of them goes above 0
(i.e. an apartment becomes available / a reservation falls through).

Setup
-----
1. Create a Telegram bot:
   - Message @BotFather on Telegram -> /newbot -> follow prompts -> copy the token
   - Message your new bot once (anything, e.g. "hi")
   - Get your chat id: visit
     https://api.telegram.org/bot<TOKEN>/getUpdates
     after messaging the bot, and read the "chat":{"id": ...} value
2. Set the two environment variables below (or edit the constants directly):
     TELEGRAM_BOT_TOKEN
     TELEGRAM_CHAT_ID
3. Run this script on a schedule (cron, systemd timer, or GitHub Actions —
   see the bottom of this file for a sample workflow). Every 10-15 minutes
   is plenty and is polite to the site.

State is stored in state.json next to this script, so re-runs only notify
on *changes*, not every time free>0 persists.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

URL = "https://www.campus-gardens.de/en/rent"
STATE_FILE = Path(__file__).parent / "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

HOUSES = {
    "A": "Asia",
    "B": "Australia",
    "C": "Europe",
    "D": "America",
}


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags_to_text(html: str) -> str:
    # crude but dependency-free: strip scripts/styles, then tags, collapse whitespace
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text


def parse_free_counts(text: str) -> dict:
    """
    Looks for blocks like:
        House A
        occupied: 130
        reserved: 0
        free: 0
        Asia
    Returns {"A": {"occupied": int, "reserved": int, "free": int}, ...}
    """
    results = {}
    for letter in HOUSES:
        # find "House <letter>" then the next occupied/reserved/free triplet
        m = re.search(
            rf"House\s+{letter}\b.*?occupied:\s*(\d+)\s*reserved:\s*(\d+)\s*free:\s*(\d+)",
            text,
            re.S | re.I,
        )
        if m:
            results[letter] = {
                "occupied": int(m.group(1)),
                "reserved": int(m.group(2)),
                "free": int(m.group(3)),
            }
    return results


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[warn] Telegram not configured, printing instead:\n" + message)
        return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        api_url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as e:
        print(f"[error] Telegram send failed: {e}", file=sys.stderr)


def main():
    try:
        html = fetch_html(URL)
    except Exception as e:
        print(f"[error] Could not fetch page: {e}", file=sys.stderr)
        sys.exit(1)

    text = strip_tags_to_text(html)
    current = parse_free_counts(text)

    if not current:
        print("[error] Could not parse any house data — page structure may have changed.")
        sys.exit(1)

    previous = load_state()

    newly_free = []
    for letter, counts in current.items():
        prev_free = previous.get(letter, {}).get("free", 0)
        if counts["free"] > prev_free:
            newly_free.append((letter, HOUSES[letter], prev_free, counts["free"]))

    if newly_free:
        lines = ["🏠 Campus Gardens Heidelberg — apartment(s) became available!"]
        for letter, name, prev, now in newly_free:
            lines.append(f"House {letter} ({name}): free went {prev} -> {now}")
        lines.append(URL)
        message = "\n".join(lines)
        print(message)
        send_telegram(message)
    else:
        print("No new availability. Current state:")
        for letter, counts in current.items():
            print(f"  House {letter} ({HOUSES[letter]}): {counts}")

    save_state(current)


if __name__ == "__main__":
    main()
