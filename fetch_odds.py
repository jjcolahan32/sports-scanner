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


if __name__ == "__main__":
    for k, v in mlb_moneylines().items():
        print(f"{v['away']} ({v['away_ml']}) @ {v['home']} ({v['home_ml']})")
