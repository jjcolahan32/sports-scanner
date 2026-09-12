"""backtest_market_prob_cfb.py — CFB half of the rating->win-probability calibration
(see backtest_market_prob.py for the NFL half and the shared fit_logistic()/log_loss()/
calibration_table() math).

Needs CFBD_API_KEY and real internet access -- run via GitHub Actions
(.github/workflows/probe.yml pattern), not this sandbox.

Look-ahead-bias note: CFBD's /ratings/sp returns one rating per team per season -- a
season's own SP+ already reflects THAT season's results, so using season Y's SP+ to
"predict" games played during season Y would leak the future into the prediction (a game
in week 3 scored with a rating that already knows about weeks 4-15). The live model
doesn't have this problem (it fetches whatever SP+ CFBD currently reports, which at any
live moment only reflects games actually played so far) -- but a backtest replaying
history can't reconstruct "SP+ as CFBD would have reported it that week" without a
week-by-week snapshot CFBD doesn't expose. So this backtests the leak-free proxy CFBD's
data granularity actually allows: season Y-1's FINAL SP+ predicting season Y's games.
That's a noisier, lagged proxy for a team's current quality than the live model's
in-season current-year SP+ -- so if this still shows real predictive power, the live
version (better-informed, same season) should be at least as good, plausibly better.
"""
import fetch_cfb
from backtest_market_prob import fit_logistic, log_loss, calibration_table


def cfb_pairs(seasons):
    pairs = []
    ratings_cache = {}
    for season in seasons:
        if season not in ratings_cache:
            ratings_cache[season] = fetch_cfb.team_ratings(season)
        prior_ratings = ratings_cache[season]
        games = fetch_cfb.season_games(season + 1, season_type="regular")
        for g in games:
            if g["home_score"] is None or g["away_score"] is None:
                continue
            hr_row, ar_row = prior_ratings.get(g["home"]), prior_ratings.get(g["away"])
            if not hr_row or not ar_row:
                continue
            hr, ar = hr_row.get("rating"), ar_row.get("rating")
            if hr is None or ar is None:
                continue
            home_win = 1 if g["home_score"] > g["away_score"] else (0 if g["home_score"] < g["away_score"] else None)
            if home_win is None:
                continue
            pairs.append((hr - ar, home_win))
    return pairs


if __name__ == "__main__":
    seasons = list(range(2015, 2025))  # season Y's SP+ predicts season Y+1's games
    print(f"Pulling CFBD games/ratings for seasons {seasons[0]}-{seasons[-1]+1}...")
    pairs = cfb_pairs(seasons)
    print(f"{len(pairs)} (rating_diff, home_win) pairs with real prior-season ratings")

    k, b = fit_logistic(pairs)
    print(f"\nFit: P(home_win) = sigmoid({k:.4f} * rating_diff + {b:.4f})")
    print(f"log-loss: {log_loss(pairs, k, b):.4f}  (0.693 = coin-flip baseline)")

    print("\nCalibration (10 buckets, sorted by predicted prob):")
    print(f"{'avg predicted':>14}  {'avg actual':>10}  {'n':>6}")
    for pred, actual, n in calibration_table(pairs, k, b):
        print(f"{pred:14.3f}  {actual:10.3f}  {n:6d}")
