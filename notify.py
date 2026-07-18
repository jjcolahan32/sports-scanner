"""
notify.py — push a message to your phone via ntfy.sh (free, no account).

Setup: install the ntfy app (iOS/Android), subscribe to a private topic name
you choose (treat it like a password — make it unguessable), then set
NTFY_TOPIC to that same name. That's it.
"""
import os, urllib.request


def push(title, body, priority="high", tag="baseball"):
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic:
        raise RuntimeError("Set NTFY_TOPIC to your private ntfy topic name")
    url = f"https://ntfy.sh/{topic}"
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"Title": title, "Priority": priority,
                 "Tags": tag, "User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


if __name__ == "__main__":
    print("status:", push("Card scanner test", "If you see this, notifications work."))
