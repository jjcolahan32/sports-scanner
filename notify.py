"""
notify.py — push a message to your phone via ntfy.sh (free, no account).

Setup: install the ntfy app (iOS/Android), subscribe to a private topic name
you choose (treat it like a password — make it unguessable), then set
NTFY_TOPIC to that same name. That's it.
"""
import os, json, urllib.request


PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5, "urgent": 5}


def push(title, body, priority="high", tag="baseball"):
    """Uses ntfy's JSON publish format (not the Title/Tags header form) so
    emoji in the title (e.g. scan.py's '⚾ 2 play(s)...') don't crash on
    Python's http.client, which restricts header values to Latin-1. Unlike
    the header form, ntfy's JSON API requires priority as a number (1-5),
    not the word form, so map it here."""
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        raise RuntimeError("Set NTFY_TOPIC to your private ntfy topic name")
    payload = json.dumps({
        "topic": topic, "title": title, "message": body,
        "priority": PRIORITIES.get(priority, priority),
        "tags": [tag] if isinstance(tag, str) else tag,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://ntfy.sh/", data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


if __name__ == "__main__":
    print("status:", push("Card scanner test", "If you see this, notifications work."))
