"""
selftest.py — dry-run the live integrations (MLB feed, odds feed, ntfy push,
Discord webhook, Savant, weather) and print pass/fail for each. Re-run
anytime with `python selftest.py`.

Needs ODDS_API_KEY and NTFY_TOPIC set in the environment for the odds/notify
checks (required channels -- FAIL if missing). DISCORD_WEBHOOK_URL is
optional (SKIP if missing, since it's an add-on channel alongside ntfy) --
the notify/discord checks send a real push to confirm each channel is wired
up end to end.
"""
import os, sys

import fetch_mlb, fetch_odds, fetch_savant, fetch_weather, ballparks, notify, discord_notify


def main():
    results = []

    games = []
    try:
        games = fetch_mlb.todays_games()
        sample = f"{games[0]['away']} @ {games[0]['home']}" if games else "no games today"
        print(f"PASS  fetch_mlb.todays_games — {len(games)} game(s), e.g. {sample}")
        results.append(True)
    except Exception as e:
        print(f"FAIL  fetch_mlb.todays_games — {e}")
        results.append(False)

    odds = {}
    if not os.environ.get("ODDS_API_KEY"):
        print("FAIL  fetch_odds.mlb_moneylines — ODDS_API_KEY not set")
        results.append(False)
    else:
        try:
            odds = fetch_odds.mlb_moneylines()
            if not odds:
                raise RuntimeError("no lines returned")
            print(f"PASS  fetch_odds.mlb_moneylines — {len(odds)} game(s) with lines")
            results.append(True)
        except Exception as e:
            print(f"FAIL  fetch_odds.mlb_moneylines — {e}")
            results.append(False)

    if not os.environ.get("NTFY_TOPIC"):
        print("FAIL  notify.push — NTFY_TOPIC not set")
        results.append(False)
    else:
        try:
            status = notify.push("Selftest", "selftest.py: this push confirms ntfy is wired up.")
            if status != 200:
                raise RuntimeError(f"unexpected status {status}")
            print(f"PASS  notify.push — sent, status {status}")
            results.append(True)
        except Exception as e:
            print(f"FAIL  notify.push — {e}")
            results.append(False)

    try:
        stats = fetch_savant.season_pitcher_stats()
        flat = [e for lst in stats.values() for e in lst]
        if not flat:
            raise RuntimeError("no pitcher stats returned")
        print(f"PASS  fetch_savant.season_pitcher_stats — {len(flat)} pitchers "
              f"(unofficial free endpoint — a FAIL here doesn't mean the rest is broken)")
        results.append(True)
    except Exception as e:
        print(f"FAIL  fetch_savant.season_pitcher_stats — {e} "
              f"(unofficial free endpoint — scan.py just skips the dynamic layer when this happens)")
        results.append(False)

    if not os.environ.get("DISCORD_WEBHOOK_URL"):
        print("SKIP  discord_notify.push — DISCORD_WEBHOOK_URL not set (optional channel)")
    else:
        try:
            ok = discord_notify.push("Selftest", "selftest.py: this push confirms the Discord webhook is wired up.")
            if not ok:
                raise RuntimeError("push returned False")
            print("PASS  discord_notify.push — sent")
            results.append(True)
        except Exception as e:
            print(f"FAIL  discord_notify.push — {e}")
            results.append(False)

    try:
        park = ballparks.for_team("Colorado Rockies")
        from datetime import datetime, timezone
        fc = fetch_weather.forecast_at(park["lat"], park["lon"], datetime.now(timezone.utc))
        if not fc:
            raise RuntimeError("no forecast period returned")
        print(f"PASS  fetch_weather.forecast_at — Coors Field now: {fc['temp_f']}F, "
              f"{fc['wind_mph']}mph, {fc['short']}")
        results.append(True)
    except Exception as e:
        print(f"FAIL  fetch_weather.forecast_at — {e}")
        results.append(False)

    # Bonus: reuses the feeds already fetched above, no extra API calls.
    if games and odds:
        unmatched = [f"{g['away']} @ {g['home']}" for g in games
                     if (fetch_odds._norm(g["away"]), fetch_odds._norm(g["home"])) not in odds]
        ok = len(unmatched) <= 1   # allow one game whose line just hasn't posted yet
        detail = f"{len(games) - len(unmatched)}/{len(games)} matched"
        if unmatched:
            detail += f" — unmatched: {', '.join(unmatched)}"
        print(f"{'PASS' if ok else 'FAIL'}  team-name matching (bonus) — {detail}")
        results.append(ok)
    else:
        print("SKIP  team-name matching (bonus) — needs both feeds above to pass first")

    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
