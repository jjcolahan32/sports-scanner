"""
fetch_odds.py — consensus MLB moneyline (h2h) per game.
Source: The Odds API free tier (NBA+MLB, h2h). Needs ODDS_API_KEY env var.

Returns a dict keyed by a normalized "away@home" plus per-team American odds.
These are CONSENSUS lines to flag dog/fav + rough price. Confirm the exact
play610 number yourself before placing.
"""
import os, json, urllib.request, urllib.parse

BASE = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"


def _norm(name):
    return name.lower().split()[-1]  # last word = nickname, e.g. "Phillies"


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
        out[(_norm(away), _norm(home))] = {
            "home": home, "away": away,
            "home_ml": prices.get(_norm(home), [None])[0],
            "away_ml": prices.get(_norm(away), [None])[0],
        }
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
        out[(_norm(away), _norm(home))] = {
            "home": home, "away": away, "point": point,
            "over_price": over_price, "under_price": under_price,
        }
    return out


if __name__ == "__main__":
    for k, v in mlb_moneylines().items():
        print(f"{v['away']} ({v['away_ml']}) @ {v['home']} ({v['home_ml']})")
