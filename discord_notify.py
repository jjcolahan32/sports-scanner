"""
discord_notify.py — push the same picks to a Discord channel via a webhook,
alongside (not instead of) the ntfy phone push.

Setup: in Discord, go to the target channel -> Edit Channel -> Integrations
-> Webhooks -> New Webhook. Name it (e.g. "Card Scanner"), copy the Webhook
URL, and set it as the DISCORD_WEBHOOK_URL secret. No bot invite, no OAuth,
no persistent process required -- a webhook is just a POST endpoint Discord
renders as a message from that identity in the channel.

Optional by design: if DISCORD_WEBHOOK_URL isn't set, or the POST fails,
this fails soft (prints a note, returns False) rather than raising -- a
Discord outage or missing webhook should never break the scan/grade job,
since ntfy is still the primary channel.
"""
import os, json, urllib.request

DISCORD_MAX = 2000  # Discord's hard limit on a single message's content
SENT_FILE = "discord_sent.json"


def push(title, body, webhook_url=None):
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return False
    text = f"**{title}**\n{body}"
    if len(text) > DISCORD_MAX:
        text = text[:DISCORD_MAX - 20] + "\n… (truncated)"
    payload = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "card-scanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"Discord push failed (non-fatal, ntfy is still primary): {e}")
        return False


def record_sent(game_pks):
    """Persist which games' PLAY alert actually reached Discord (cumulative,
    never resets by date -- game_pks don't repeat across a season). grade.py
    reads this so the nightly Discord recap only reports on plays Discord
    actually saw fire, instead of every play that day regardless of channel."""
    try:
        with open(SENT_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"game_pks": []}
    seen = {str(x) for x in data.get("game_pks", [])}
    seen.update(str(x) for x in game_pks)
    data["game_pks"] = sorted(seen)
    with open(SENT_FILE, "w") as f:
        json.dump(data, f)


def load_sent():
    try:
        with open(SENT_FILE) as f:
            data = json.load(f)
        return {str(x) for x in data.get("game_pks", [])}
    except FileNotFoundError:
        return set()


if __name__ == "__main__":
    ok = push("Card scanner test", "If you see this in Discord, the webhook is wired up.")
    print("posted to Discord" if ok else "not configured, or the post failed -- see message above")
