"""
fetch_savant.py — season ERA vs xERA (Statcast expected ERA) per pitcher, used to
flag mismatches for starters who AREN'T on the hand-vetted LEGIT_ARMS/MIRAGES
lists in model.py. This is the automated version of the same comparison RULES.md
says built those lists in the first place (ERA vs xERA/FIP/xFIP/SIERA/xwOBA) —
FIP/xFIP/SIERA aren't available from any free API (FIP/xFIP aren't in Savant's
stat set, SIERA is FanGraphs-only), so this covers ERA, xERA, and xwOBA.

Source: Baseball Savant's public custom-leaderboard CSV export. Free, no key —
but NOT a documented/stable API like MLB StatsAPI or The Odds API. It can change
shape or disappear without notice. Callers should treat a failure here as "skip
the dynamic layer for this run", never as a reason to fail the whole scan.
"""
import csv, io, urllib.request, urllib.parse
from datetime import datetime, timezone

BASE = "https://baseballsavant.mlb.com/leaderboard/custom"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (card-scanner/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8-sig")


def season_pitcher_stats(year=None, min_pa=10):
    """Return {last_name_lower: [{first, last, era, xera, xwoba, gap}, ...]}.
    Grouped by last name since two pitchers can share a surname. gap = era - xera:
    strongly positive -> ERA overstates how bad he's been (reverse-mirage, back him);
    strongly negative -> ERA overstates how good he's been (mirage, fade him)."""
    year = year or datetime.now(timezone.utc).year
    q = urllib.parse.urlencode({
        "year": year, "type": "pitcher", "min": min_pa,
        "selections": "p_era,xera,xwoba", "chart": "false",
        "x": "xera", "y": "xera", "r": "no", "chartType": "beeswarm", "csv": "true",
    })
    text = _get(f"{BASE}?{q}")
    reader = csv.DictReader(io.StringIO(text))
    out = {}
    for row in reader:
        full = row.get("last_name, first_name", "")
        if "," not in full:
            continue
        last, first = [s.strip() for s in full.split(",", 1)]
        era, xera = row.get("p_era"), row.get("xera")
        if not era or not xera:
            continue
        try:
            era_f, xera_f = float(era), float(xera)
        except ValueError:
            continue
        entry = {"first": first, "last": last, "era": era_f, "xera": xera_f,
                 "xwoba": row.get("xwoba"), "gap": round(era_f - xera_f, 2)}
        out.setdefault(last.lower(), []).append(entry)
    return out


if __name__ == "__main__":
    stats = season_pitcher_stats()
    flat = [e for lst in stats.values() for e in lst]
    print(f"{len(flat)} pitchers loaded")
    flat.sort(key=lambda e: e["gap"])
    print("\nBiggest mirages (ERA much better than xERA -- fade candidates):")
    for e in flat[:5]:
        print(f"  {e['first']} {e['last']}: ERA {e['era']} vs xERA {e['xera']} ({e['gap']:+.2f})")
    print("\nBiggest reverse-mirages (ERA much worse than xERA -- back candidates):")
    for e in flat[-5:]:
        print(f"  {e['first']} {e['last']}: ERA {e['era']} vs xERA {e['xera']} ({e['gap']:+.2f})")
