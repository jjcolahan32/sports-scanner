"""
discord_status.py — on-demand: post the current cumulative Discord-tracked
record to Discord right now, without waiting for the next grading run.
Same "Running record" line grade.py's real recap uses -- useful to preview
formatting or just check in on where things stand.

Usage: DISCORD_WEBHOOK_URL="..." python3 discord_status.py
(or DISCORD_GRADING_WEBHOOK_URL="..." if that's set up as a separate channel)
"""
import os

import discord_notify
from grade import load_json, LEDGER_FILE, blank_ledger, _migrate


def main():
    ledger = _migrate(load_json(LEDGER_FILE, blank_ledger()))
    dr = ledger["discord_record"]
    running = f"{dr['w']}-{dr['l']}" + (f", {dr['push']} push" if dr.get("push") else "")
    body = f"Running record: {running} ({ledger['discord_units']:+.2f}u)"
    grading_webhook = os.environ.get("DISCORD_GRADING_WEBHOOK_URL") or None
    ok = discord_notify.push("📊 Current standings", body, webhook_url=grading_webhook)
    print(("posted to Discord: " if ok else "not configured, or the post failed: ") + body)


if __name__ == "__main__":
    main()
