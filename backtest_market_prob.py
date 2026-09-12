"""backtest_market_prob.py — calibrate rating_diff -> win probability for the planned
market-value category (cat_market_value, not yet built). Fits a 2-parameter logistic
model P(home_win) = sigmoid(k * rating_diff + b) against real historical games, using
the SAME in-season rolling rating fetch_nfl.team_power_ratings()/fetch_cfb.team_ratings()
already compute -- so the backtest measures exactly the signal the live model would see,
not some idealized version of it.

No numpy/scipy in this environment -- Newton-Raphson by hand (2 parameters, converges in
a handful of iterations, no library needed).

NFL runs fully offline (nflverse needs no key). CFB needs CFBD_API_KEY -- see
backtest_market_prob_cfb.py, run via GitHub Actions since this sandbox can't reach CFBD.
"""
import functools
import math
from collections import defaultdict

import fetch_nfl

# season_games(year) re-fetches nflverse's entire multi-decade games.csv from the network
# on every call regardless of the year filter -- fine for the live scanner (one call per
# scan), wasteful here where we call it once per backtest season. Memoize the raw fetch
# so the network is hit exactly once for the whole backtest.
fetch_nfl._get_csv = functools.lru_cache(maxsize=4)(fetch_nfl._get_csv)


def fit_logistic(pairs, iters=25):
    """pairs: [(x, y)], y in {0,1}. Returns (k, b) for P = sigmoid(k*x + b), fit by
    Newton-Raphson (2 params, converges fast)."""
    k, b = 0.0, 0.0
    for _ in range(iters):
        g_k = g_b = h_kk = h_kb = h_bb = 0.0
        for x, y in pairs:
            z = k * x + b
            p = 1.0 / (1.0 + math.exp(-z)) if z > -700 else 0.0
            w = p * (1 - p)
            g_k += (p - y) * x
            g_b += (p - y)
            h_kk += w * x * x
            h_kb += w * x
            h_bb += w
        det = h_kk * h_bb - h_kb * h_kb
        if abs(det) < 1e-12:
            break
        # theta -= H^-1 @ g, H^-1 for [[h_kk,h_kb],[h_kb,h_bb]]
        dk = (h_bb * g_k - h_kb * g_b) / det
        db = (-h_kb * g_k + h_kk * g_b) / det
        k -= dk
        b -= db
    return k, b


def log_loss(pairs, k, b):
    total = 0.0
    for x, y in pairs:
        z = k * x + b
        p = 1.0 / (1.0 + math.exp(-z)) if -700 < z < 700 else (1.0 if z > 0 else 0.0)
        p = min(max(p, 1e-9), 1 - 1e-9)
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(pairs)


def calibration_table(pairs, k, b, n_buckets=10):
    scored = []
    for x, y in pairs:
        z = k * x + b
        p = 1.0 / (1.0 + math.exp(-z)) if -700 < z < 700 else (1.0 if z > 0 else 0.0)
        scored.append((p, y))
    scored.sort()
    n = len(scored)
    rows = []
    for i in range(n_buckets):
        lo, hi = (i * n) // n_buckets, ((i + 1) * n) // n_buckets
        chunk = scored[lo:hi]
        if not chunk:
            continue
        avg_pred = sum(p for p, _ in chunk) / len(chunk)
        avg_actual = sum(y for _, y in chunk) / len(chunk)
        rows.append((avg_pred, avg_actual, len(chunk)))
    return rows


def _rolling_ratings(games_so_far):
    """Inlined copy of fetch_nfl.team_power_ratings()'s math (avg scoring margin across
    completed games so far) -- computed here purely in-memory against an already-fetched
    game list, since calling the real function per-week would re-fetch nflverse's entire
    multi-decade CSV from the network on every single call."""
    margins = defaultdict(list)
    for g in games_so_far:
        hs, aws = g["home_score"], g["away_score"]
        if hs is None or aws is None:
            continue
        margins[g["home"]].append(hs - aws)
        margins[g["away"]].append(aws - hs)
    return {team: sum(m) / len(m) for team, m in margins.items() if m}


def nfl_pairs(seasons):
    """(rating_diff, home_win) pairs across seasons, ratings computed in-season only
    from games completed BEFORE the game being predicted -- identical method to
    scan_nfl.py's live use of fetch_nfl.team_power_ratings(through_week=...), so this
    calibrates exactly the signal the live model sees, not a look-ahead-biased version.
    One network fetch total (season_games() internally hits nflverse once), everything
    else computed in-memory."""
    pairs = []
    by_season = defaultdict(list)
    for season in seasons:
        for g in fetch_nfl.season_games(season):
            if g["game_type"] != "REG":
                continue
            by_season[season].append(g)

    for season, games in by_season.items():
        games.sort(key=lambda g: (int(g["week"]), g["start_utc"] or ""))
        for i, g in enumerate(games):
            week = int(g["week"])
            if week <= 1 or g["home_score"] is None or g["away_score"] is None:
                continue
            prior = [gg for gg in games[:i] if int(gg["week"]) < week]
            ratings = _rolling_ratings(prior)
            hr, ar = ratings.get(g["home"]), ratings.get(g["away"])
            if hr is None or ar is None:
                continue
            home_win = 1 if g["home_score"] > g["away_score"] else (0 if g["home_score"] < g["away_score"] else None)
            if home_win is None:
                continue  # tie, drop
            pairs.append((hr - ar, home_win))
    return pairs


if __name__ == "__main__":
    seasons = set(range(2015, 2026))
    print(f"Pulling nflverse games for seasons {min(seasons)}-{max(seasons)}...")
    pairs = nfl_pairs(seasons)
    print(f"{len(pairs)} (rating_diff, home_win) pairs with real ratings available")

    k, b = fit_logistic(pairs)
    print(f"\nFit: P(home_win) = sigmoid({k:.4f} * rating_diff + {b:.4f})")
    print(f"log-loss: {log_loss(pairs, k, b):.4f}  (0.693 = coin-flip baseline)")

    print("\nCalibration (10 buckets, sorted by predicted prob):")
    print(f"{'avg predicted':>14}  {'avg actual':>10}  {'n':>6}")
    for pred, actual, n in calibration_table(pairs, k, b):
        print(f"{pred:14.3f}  {actual:10.3f}  {n:6d}")
