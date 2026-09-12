"""
notify.py — push a message to your phone via ntfy.sh (free, no account).

Setup: install the ntfy app (iOS/Android), subscribe to a private topic name
you choose (treat it like a password — make it unguessable), then set
NTFY_TOPIC to that same name. That's it.
"""
import os, json, urllib.request


PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5, "urgent": 5}

# ntfy.sh's hosted publish endpoint 413s once the JSON payload gets too big (confirmed
# live: a CFB slate-day backlog of new plays crashed scan_cfb.py's whole run on this --
# and because the workflow's persist step only runs after a successful scan step, that
# crash silently threw away the day's entire graded card, not just the notification).
# Stay comfortably under ntfy's ~4096-byte message-length limit so title/tags overhead
# doesn't tip a nearly-full chunk over.
MAX_MESSAGE_BYTES = 3000


def push(title, body, priority="high", tag="baseball", topic=None):
    """Uses ntfy's JSON publish format (not the Title/Tags header form) so
    emoji in the title (e.g. scan.py's '⚾ 2 play(s)...') don't crash on
    Python's http.client, which restricts header values to Latin-1. Unlike
    the header form, ntfy's JSON API requires priority as a number (1-5),
    not the word form, so map it here.

    topic defaults to NTFY_TOPIC (every existing MLB call site) -- pass an
    explicit topic (e.g. NTFY_TOPIC_FOOTBALL) to route to a different feed
    without touching those call sites.

    A body over MAX_MESSAGE_BYTES is split into multiple sequential pushes (see
    _split_body) rather than crashing the caller's whole scan on a 413 -- returns the
    last chunk's status, same contract single-push callers already rely on."""
    topic = topic or os.environ.get("NTFY_TOPIC", "")
    if not topic:
        raise RuntimeError("Set NTFY_TOPIC to your private ntfy topic name")
    chunks = _split_body(body, MAX_MESSAGE_BYTES)
    status = None
    for i, chunk in enumerate(chunks):
        chunk_title = title if len(chunks) == 1 else f"{title} ({i + 1}/{len(chunks)})"
        status = _post(chunk_title, chunk, priority, tag, topic)
    return status


def _split_body(body, max_bytes):
    """Split on the blank-line-separated blocks every caller here already uses (one per
    play/pick) so a chunk boundary never lands mid-play. Falls back to a single
    over-budget chunk if one block alone exceeds max_bytes -- pathological (a single
    play's text that big), not worth hard-slicing mid-sentence for."""
    blocks = body.split("\n\n")
    chunks, current = [], ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if current and len(candidate.encode("utf-8")) > max_bytes:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def _post(title, body, priority, tag, topic):
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
