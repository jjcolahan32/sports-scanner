"""
fetch_teamstats.py — team-level bullpen ERA and lineup (batting) strength,
used as a supporting-cast confirmation check on top of the starter-gap edge
in scan.py: a great starter matchup can still get erased by a bad bullpen,
and a great pitching mismatch doesn't matter if the lineup can't score.

Source: MLB Stats API (statsapi.mlb.com) -- the same free, documented,
unlimited (no quota) API already powering fetch_mlb.py. Bullpen-only stats
come from the official "rp" (Reliever) situational split; team batting is
full-season aggregate (there's no free per-game confirmed-lineup source,
so season OPS is the best available proxy for lineup strength).

Loops over all 30 teams individually rather than the bulk /api/v1/stats
endpoint -- that endpoint returned multiple inconsistent duplicate rows per
team when filtered by sitCodes (a real, observed quirk), while the
per-team /teams/{id}/stats endpoint returns exactly one clean split every
time. 30 quick requests to a free unlimited API is a non-issue.
"""
import urllib.request, json
from datetime import datetime, timezone

BASE = "https://statsapi.mlb.com/api/v1"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "card-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def all_team_ids():
    d = _get(f"{BASE}/teams?sportId=1")
    return {t["id"]: t["name"] for t in d["teams"]}


def team_bullpen_era(team_id, year=None):
    year = year or datetime.now(timezone.utc).year
    d = _get(f"{BASE}/teams/{team_id}/stats?stats=statSplits&group=pitching&season={year}&sitCodes=rp")
    splits = d.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return None
    try:
        return float(splits[0]["stat"]["era"])
    except (KeyError, ValueError):
        return None


def team_batting_ops(team_id, year=None):
    year = year or datetime.now(timezone.utc).year
    d = _get(f"{BASE}/teams/{team_id}/stats?stats=season&group=hitting&season={year}")
    splits = d.get("stats", [{}])[0].get("splits", [])
    if not splits:
        return None
    try:
        return float(splits[0]["stat"]["ops"])
    except (KeyError, ValueError):
        return None


def all_team_stats(year=None):
    """{team_name: {"bullpen_era": float|None, "batting_ops": float|None}} for
    all 30 teams, keyed by full team name (matches fetch_mlb.py's game dicts).
    One failed team doesn't sink the rest -- missing stats for a given team
    just means that team's games skip the supporting-cast check that run."""
    year = year or datetime.now(timezone.utc).year
    out = {}
    for team_id, name in all_team_ids().items():
        try:
            era = team_bullpen_era(team_id, year)
        except Exception:
            era = None
        try:
            ops = team_batting_ops(team_id, year)
        except Exception:
            ops = None
        out[name] = {"bullpen_era": era, "batting_ops": ops}
    return out


if __name__ == "__main__":
    stats = all_team_stats()
    ok = {k: v for k, v in stats.items() if v["bullpen_era"] is not None and v["batting_ops"] is not None}
    print(f"{len(ok)}/{len(stats)} teams loaded cleanly")
    by_era = sorted(ok.items(), key=lambda kv: kv[1]["bullpen_era"])
    print("\nBest bullpens (lowest ERA):")
    for name, s in by_era[:5]:
        print(f"  {name}: {s['bullpen_era']} ERA")
    print("\nWorst bullpens (highest ERA):")
    for name, s in by_era[-5:]:
        print(f"  {name}: {s['bullpen_era']} ERA")
    by_ops = sorted(ok.items(), key=lambda kv: -kv[1]["batting_ops"])
    print("\nBest lineups (highest OPS):")
    for name, s in by_ops[:5]:
        print(f"  {name}: {s['batting_ops']} OPS")
