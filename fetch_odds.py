"""
fetch_odds.py — consensus MLB moneyline (h2h) and totals per game.
Source: The Odds API free tier. Needs ODDS_API_KEY env var.

Returns a dict keyed by normalized "away@home" team pair -> LIST of entries
(each with its own commence_time), not a single entry. MLB teams commonly
play the same opponent on consecutive days, and the API's returned window
isn't limited to "today" -- a naive last-write-wins dict silently grabbed
TOMORROW's line for a team pair playing today (and vice versa) whenever both
showed up in the same pull. Confirmed against a live pull: 14 of 30 games on
a single day collided with a next-day rematch. Callers must disambiguate by
game time via closest() -- never index this dict directly by team pair alone.
"""
import os, json, urllib.request, urllib.parse
from datetime import datetime

BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"


def _norm(name):
    return name.lower().split()[-1]  # last word = nickname, e.g. "Phillies"


def closest(entries, target_start_utc):
    """Pick the entry whose commence_time is nearest target_start_utc (the
    real game's actual start time, from MLB StatsAPI). Use this instead of
    indexing the dict directly -- a team pair can have multiple entries."""
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]
    try:
        target = datetime.fromisoformat(target_start_utc.replace("Z", "+00:00"))
    except Exception:
        return entries[0]

    def diff(e):
        try:
            t = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
            return abs((t - target).total_seconds())
        except Exception:
            return float("inf")
    return min(entries, key=diff)


def mlb_moneylines(api_key=None):
    api_key = api_key or os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY (free at the-odds-api.com)")
    q = urllib.parse.urlencode({"apiKey": api_key, "regions": "us",
                                "markets": "h2h", "oddsFormat": "american"})
    req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        events = json.loads(r.read().decode())

    out = {}
    for ev in events:
        home, away = ev.get("home_team", ""), ev.get("away_team", "")
        # median-ish: take first book's prices (consensus is close enough to flag)
        prices = {}
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m.get("key") == "h2h":
                    for oc in m.get("outcomes", []):
                        prices.setdefault(_norm(oc["name"]), []).append(oc["price"])
            if prices:
                break
        key = (_norm(away), _norm(home))
        out.setdefault(key, []).append({
            "home": home, "away": away, "commence_time": ev.get("commence_time"),
            "home_ml": prices.get(_norm(home), [None])[0],
            "away_ml": prices.get(_norm(away), [None])[0],
        })
    return out


def mlb_totals(api_key=None):
    """Consensus over/under line + prices per game. Separate request+market
    from mlb_moneylines() -- costs its own Odds API quota unit, so callers
    should fetch this less often than the moneyline scan (see scan_totals.py)."""
    api_key = api_key or os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY (free at the-odds-api.com)")
    q = urllib.parse.urlencode({"apiKey": api_key, "regions": "us",
                                "markets": "totals", "oddsFormat": "american"})
    req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        events = json.loads(r.read().decode())

    out = {}
    for ev in events:
        home, away = ev.get("home_team", ""), ev.get("away_team", "")
        point, over_price, under_price = None, None, None
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m.get("key") != "totals":
                    continue
                for oc in m.get("outcomes", []):
                    if oc["name"] == "Over":
                        point, over_price = oc.get("point"), oc["price"]
                    elif oc["name"] == "Under":
                        under_price = oc["price"]
            if point is not None:
                break
        key = (_norm(away), _norm(home))
        out.setdefault(key, []).append({
            "home": home, "away": away, "commence_time": ev.get("commence_time"),
            "point": point, "over_price": over_price, "under_price": under_price,
        })
    return out


if __name__ == "__main__":
    for k, entries in mlb_moneylines().items():
        for v in entries:
            print(f"{v['away']} ({v['away_ml']}) @ {v['home']} ({v['home_ml']}) -- {v['commence_time']}")
