"""
fetch_tennis.py — active ATP/WTA tournaments + head-to-head moneylines.

Source: The Odds API. Unlike MLB (one feed for the whole day's slate), tennis is
exposed as ~40 per-tournament sport keys (e.g. "tennis_atp_canadian_open"), each
"active" only while that tournament is actually being played. The discovery call
(/v4/sports?all=true) is free; only per-tournament odds calls cost quota, so we
check what's live before spending any.
"""
import os, json, urllib.request, urllib.parse

SPORTS = "https://api.the-odds-api.com/v4/sports/"
ODDS = "https://api.the-odds-api.com/v4/sports/{key}/odds"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _key(api_key=None):
    api_key = api_key or os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY (free at the-odds-api.com)")
    return api_key


def active_tournaments(api_key=None):
    """Free call. Return active ATP/WTA singles tournaments: [{key, title, tour}]."""
    api_key = _key(api_key)
    q = urllib.parse.urlencode({"apiKey": api_key, "all": "true"})
    data = _get(f"{SPORTS}?{q}")
    out = []
    for d in data:
        if d.get("group") != "Tennis" or not d.get("active"):
            continue
        if "Singles" not in d.get("description", ""):
            continue
        tour = "ATP" if d["key"].startswith("tennis_atp") else "WTA"
        out.append({"key": d["key"], "title": d["title"], "tour": tour})
    return out


def matches_for(tournament, api_key=None):
    """One paid call. Return h2h matches for a single active tournament key."""
    api_key = _key(api_key)
    q = urllib.parse.urlencode({"apiKey": api_key, "regions": "us",
                                "markets": "h2h", "oddsFormat": "american"})
    events = _get(f"{ODDS.format(key=tournament['key'])}?{q}")
    out = []
    for ev in events:
        home, away = ev.get("home_team", ""), ev.get("away_team", "")
        prices = {}
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m.get("key") == "h2h":
                    for oc in m.get("outcomes", []):
                        prices[oc["name"]] = oc["price"]
            if prices:
                break
        if home not in prices or away not in prices:
            continue
        out.append({
            "tournament": tournament["title"], "tour": tournament["tour"],
            "commence_time": ev.get("commence_time"),
            "player_a": home, "odds_a": prices[home],
            "player_b": away, "odds_b": prices[away],
        })
    return out


def all_active_matches(api_key=None):
    """Discover active tournaments (free), then pull odds for each (paid, one call/tournament)."""
    api_key = _key(api_key)
    matches = []
    for t in active_tournaments(api_key):
        matches.extend(matches_for(t, api_key))
    return matches


if __name__ == "__main__":
    tournaments = active_tournaments()
    if not tournaments:
        print("No active ATP/WTA tournaments right now.")
    for t in tournaments:
        print(f"ACTIVE: {t['tour']} {t['title']} ({t['key']})")
        for m in matches_for(t):
            print(f"   {m['player_a']} ({m['odds_a']:+d}) vs "
                  f"{m['player_b']} ({m['odds_b']:+d})")
