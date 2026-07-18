"""
backfill_discord.py — on-demand catch-up: post any already-logged plays
(from today's card_<date>.json / card_totals_<date>.json) whose game hasn't
started yet to Discord. ntfy already got these when they first fired; this
just backfills the Discord channel without re-scanning or re-grading
anything -- useful right after adding the webhook mid-day, or after a
Discord outage.

Usage: DISCORD_WEBHOOK_URL="..." python3 backfill_discord.py
"""
from datetime import datetime, timezone

import discord_notify
from scan import load_json, _star_str, _today


def _not_started(play, now):
    start = datetime.fromisoformat(play["start_utc"].replace("Z", "+00:00"))
    return start > now


def _line(play):
    tag = " [TOTALS]" if "side" in play else f" [{play.get('rlm_tag', 'NEUTRAL')}]"
    return (f"PLAY: {play['selection']} {play['odds']:+d} "
            f"(risk {play['risk']}u/win {play['to_win']}u){tag}  {_star_str(play.get('stars'))}")


def main():
    now = datetime.now(timezone.utc)
    lines = []
    for path in (f"card_{_today()}.json", f"card_totals_{_today()}.json"):
        card = load_json(path, {"plays": []})
        for play in card.get("plays", []):
            if play["verdict"] != "PLAY" or not _not_started(play, now):
                continue
            lines.append(_line(play))

    if not lines:
        print("No logged plays with a game that hasn't started yet.")
        return

    body = "\n".join(lines)
    ok = discord_notify.push(f"⚾ Catch-up: {len(lines)} pending play(s)", body)
    print(("posted to Discord" if ok else "not configured, or the post failed") + "\n\n" + body)


if __name__ == "__main__":
    main()
