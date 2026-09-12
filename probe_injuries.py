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


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/college-football/team/_/id/61",
    "Origin": "https://www.espn.com",
}


def try_espn_team_list():
    for label, headers in (("plain UA", {"User-Agent": UA}), ("browser-like", BROWSER_HEADERS)):
        url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=500"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
            print(f"ESPN team list ({label}) -> OK, {len(teams)} teams")
            sample = [(t["team"]["id"], t["team"]["displayName"]) for t in teams[:5]]
            print("sample:", sample)
            return {t["team"]["displayName"]: t["team"]["id"] for t in teams}
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            print(f"ESPN team list ({label}) -> HTTP {e.code}, body: {body}")
        except Exception as e:
            print(f"ESPN team list ({label}) -> FAILED: {e}")
    return {}


def try_espn_injuries(team_id, team_name):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_id}/injuries"
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
        print(f"ESPN injuries for {team_name} ({team_id}) -> OK")
        print(json.dumps(data, indent=2)[:2000])
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        print(f"ESPN injuries for {team_name} ({team_id}) -> HTTP {e.code}, body: {body}")
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
    else:
        print("\nteam list blocked -- trying known ESPN team IDs directly anyway")
        for tid, name in ((61, "Georgia"), (333, "Alabama"), (194, "Ohio State")):
            try_espn_injuries(tid, name)


if __name__ == "__main__":
    main()
