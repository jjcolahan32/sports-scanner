"""probe_injuries.py — one-off diagnostic: does any automated source have real CFB injury
data? Tries CFBD's own API (in case an /injuries-shaped endpoint has been added since this
codebase's fetch_cfb.py was written) and ESPN's unofficial college-football injuries
endpoint (same shape as the well-known NFL one). Prints what it finds; commits nothing.
Delete once the real fetch is built and confirmed working.
"""
import json
import os
import urllib.error
import urllib.request

import fetch_cfb

UA = "football-model/1.0 (personal use)"


def try_cfbd_endpoint(path, params=None):
    try:
        data = fetch_cfb._get(path, params)
        print(f"CFBD {path} {params or ''} -> OK, {len(data) if isinstance(data, list) else 'non-list'} items")
        print(json.dumps(data[:3] if isinstance(data, list) else data, indent=2)[:1500])
    except Exception as e:
        print(f"CFBD {path} {params or ''} -> FAILED: {e}")
    print("---")


def try_espn_team_list():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=500"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        print(f"ESPN team list -> OK, {len(teams)} teams")
        sample = [(t["team"]["id"], t["team"]["displayName"]) for t in teams[:5]]
        print("sample:", sample)
        return {t["team"]["displayName"]: t["team"]["id"] for t in teams}
    except Exception as e:
        print(f"ESPN team list -> FAILED: {e}")
        return {}


def try_espn_injuries(team_id, team_name):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_id}/injuries"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        print(f"ESPN injuries for {team_name} ({team_id}) -> OK")
        print(json.dumps(data, indent=2)[:2000])
    except urllib.error.HTTPError as e:
        print(f"ESPN injuries for {team_name} ({team_id}) -> HTTP {e.code}")
    except Exception as e:
        print(f"ESPN injuries for {team_name} ({team_id}) -> FAILED: {e}")
    print("---")


def main():
    print("=== CFBD candidate injury-shaped endpoints ===")
    for path in ("/injuries", "/player/injuries", "/teams/injuries"):
        try_cfbd_endpoint(path, {"year": 2026, "week": 3})

    print("\n=== ESPN unofficial endpoint ===")
    team_ids = try_espn_team_list()
    if team_ids:
        # Try a couple of recognizable Power-4 programs, most likely to have real
        # editorial injury tracking if ESPN has any for CFB at all.
        for name in ("Georgia Bulldogs", "Alabama Crimson Tide", "Ohio State Buckeyes"):
            tid = team_ids.get(name)
            if tid:
                try_espn_injuries(tid, name)
            else:
                print(f"{name} not found in ESPN team list")


if __name__ == "__main__":
    main()
