"""send_notify.py — one-off manual ntfy push (title/body from env), used by the
manual-notify GH Actions workflow for ad-hoc pushes (recalls, consolidated ledgers)
outside the normal per-sport scan cadence. notify.push() already chunks an oversized
body on its own, so callers here don't need to split anything themselves.
"""
import os

import notify


def main():
    title = os.environ["NOTIFY_TITLE"]
    body = os.environ["NOTIFY_BODY"]
    topic = os.environ.get("NTFY_TOPIC_FOOTBALL") or os.environ["NTFY_TOPIC"]
    status = notify.push(title, body, topic=topic, tag="football")
    print(f"ntfy status: {status}")


if __name__ == "__main__":
    main()
