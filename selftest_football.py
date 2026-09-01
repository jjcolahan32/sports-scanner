"""
selftest_football.py — dry-run the live football integrations (nflverse, CFBD, Odds
API, ntfy, weather) and print pass/fail for each, mirroring selftest.py's style for the
MLB build. Re-run anytime with `python selftest_football.py`.

Needs ODDS_API_KEY, CFBD_API_KEY, and NTFY_TOPIC_FOOTBALL set in the environment for
those checks (FAIL if missing -- these are the required channels/sources for football).
nflverse and NWS weather need no key at all.
"""
import os, sys
from datetime import datetime, timezone

import fetch_nfl, fetch_cfb, fetch_odds_football, fetch_weather, stadiums_football, model_football, notify


def main():
    results = []

    nfl_games = []
    try:
        nfl_games = fetch_nfl.week_games()
        sample = f"{nfl_games[0]['away']} @ {nfl_games[0]['home']}" if nfl_games else "no games this week"
        print(f"PASS  fetch_nfl.week_games — {len(nfl_games)} game(s), e.g. {sample}")
        results.append(True)
    except Exception as e:
        print(f"FAIL  fetch_nfl.week_games — {e}")
        results.append(False)

    if not os.environ.get("CFBD_API_KEY"):
        print("FAIL  fetch_cfb.week_games — CFBD_API_KEY not set (free at collegefootballdata.com/key)")
        results.append(False)
    else:
        try:
            cfb_games = fetch_cfb.week_games()
            sample = f"{cfb_games[0]['away']} @ {cfb_games[0]['home']}" if cfb_games else "no games this week"
            print(f"PASS  fetch_cfb.week_games — {len(cfb_games)} game(s), e.g. {sample}")
            results.append(True)
        except Exception as e:
            print(f"FAIL  fetch_cfb.week_games — {e}")
            results.append(False)

    if not os.environ.get("ODDS_API_KEY"):
        print("FAIL  fetch_odds_football.football_odds — ODDS_API_KEY not set")
        results.append(False)
    else:
        for sport in ("nfl", "cfb"):
            try:
                odds = fetch_odds_football.football_odds(sport)
                n = sum(len(v) for v in odds.values())
                print(f"PASS  fetch_odds_football.football_odds('{sport}') — {n} game(s) with lines")
                results.append(True)
            except Exception as e:
                print(f"FAIL  fetch_odds_football.football_odds('{sport}') — {e}")
                results.append(False)

    if not os.environ.get("NTFY_TOPIC_FOOTBALL"):
        print("FAIL  notify.push (football topic) — NTFY_TOPIC_FOOTBALL not set")
        results.append(False)
    else:
        try:
            status = notify.push("Selftest", "selftest_football.py: this push confirms the football ntfy topic is wired up.",
                                  topic=os.environ["NTFY_TOPIC_FOOTBALL"], tag="football")
            if status != 200:
                raise RuntimeError(f"unexpected status {status}")
            print(f"PASS  notify.push (football topic) — sent, status {status}")
            results.append(True)
        except Exception as e:
            print(f"FAIL  notify.push (football topic) — {e}")
            results.append(False)

    try:
        kc = stadiums_football.for_team("KC")
        fc = fetch_weather.forecast_at(kc["lat"], kc["lon"], datetime.now(timezone.utc))
        if not fc:
            raise RuntimeError("no forecast period returned")
        print(f"PASS  fetch_weather.forecast_at — Arrowhead now: {fc['temp_f']}F, {fc['wind_mph']}mph, {fc['short']}")
        results.append(True)
    except Exception as e:
        print(f"FAIL  fetch_weather.forecast_at — {e}")
        results.append(False)

    # Bonus, no network -- exercises model_football.py's 2+-category stacking gate
    # directly (RULES_FOOTBALL.md Section 1's core rule).
    demo_confirmed = {"sport": "nfl", "home": "KC", "away": "DEN",
                       "home_injury_burden": 0.0, "away_injury_burden": 3.0,
                       "home_rating": 6.0, "away_rating": -2.0,
                       "home_rest": 7, "away_rest": 7, "roof": "dome"}
    demo_note = {**demo_confirmed, "away_injury_burden": None, "home_rating": None, "away_rating": None}
    g1, g2 = model_football.grade_ml(demo_confirmed), model_football.grade_ml(demo_note)
    ok = g1["verdict"] == "CONFIRMED" and g1["side"] == "home" and g2["verdict"] in ("NOTE", "PASS")
    print(f"{'PASS' if ok else 'FAIL'}  model_football stacking gate (bonus) — "
          f"2-category={g1['verdict']}, 0-category={g2['verdict']}")
    results.append(ok)

    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
