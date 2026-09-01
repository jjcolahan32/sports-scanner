# Football Logic — Canonical Logic Source (NFL + CFB)

_Companion to `RULES.md` (MLB). Adapted from the user's football_logic_brain.md spec._
_Ledger tracked separately from MLB: `ledger_football.json` (own units, own record)._

**Phase 1 scope (this build): spreads, totals, moneylines only.** Anytime-TD player props
(category G below) are documented here for completeness but NOT wired into `model_football.py`,
`scan_nfl.py`/`scan_cfb.py`, or staking yet — fast-follow once the core engine is proven.

---

## 1. Core Philosophy

A pick only becomes **CONFIRMED** when **2+ independent signal categories stack in the same
direction.** A single injury or a single weather flag is a **NOTE** — informational only,
never staked. This mirrors the MLB model's "vetted list vs. mirage" logic: here it's a
**vetted matchup read**, built from category signals computed fresh every scan rather than a
hand-maintained list (NFL/CFB matchups don't repeat the way a starting pitcher's season stats
do, so there's no equivalent of `LEGIT_ARMS`/`MIRAGES` — every category signal is computed
live from that week's actual data).

## 2. Edge Categories & Signals

### A. Injuries
- **QB status** (out/doubtful/questionable) — heaviest single line-mover.
- **OL**, especially LT/C — pass-pro collapse risk.
- **WR1/RB1** — role/target redistribution to whoever inherits the vacated touches.
- **Front-seven pass rushers** (opponent) — pressure rate shift.
- **CB1/top safety** (opponent) — opposing pass efficiency vs. backup coverage.
- **NFL**: practice-report *trend* (DNP → Limited → Full, or reverse) matters more than a
  single day's tag. Sourced from the official weekly report (`fetch_nfl.injuries()`).
- **CFB**: no official injury report exists. Only a *confirmed* absence (announced, or
  actually seen missing from the two-deep) counts as a signal; beat-reporter rumor is
  note-only and never stacks. No automated feed for this — see `public_cfb_injuries.json`
  (optional, hand-maintained, same pattern as the MLB model's `public.json`).

### B. Weather at the Stadium
- **Wind >15mph**: favors unders, fades pass-heavy/deep-ball offenses and FG range.
- **Precipitation**: fumble rate up, favors run volume and unders.
- **Cold (<32°F)**: hurts dome teams traveling outdoors more than cold-weather teams.
- **Dome/retractable-roof games**: non-factor — don't manufacture a weather edge.
- **Altitude (Denver)**: late-game conditioning factor for road teams, more so short week.

### C. Run vs. Pass Environment Fit
- Layer weather + injury + opponent scheme to determine game-script skew.
- A run-first team forced into pass-heavy mode (or vice versa) by weather/injury is a fade.
- Connective layer between A and B — this is usually where CONFIRMED gets earned.

### D. Matchup Mismatches
- Pass rush win rate vs. OL pressure rate allowed.
- Man/zone coverage tendency vs. opposing WR route tree.
- Run-stuff rate vs. run scheme (gap vs. zone).
- Red-zone efficiency differential (offense TD% vs. defense TD% allowed).

### E. Strength of Schedule / Situational Context
- **Opponent-adjusted efficiency**, not raw record. NFL: SOS to date/remaining. CFB: always
  **conference-adjusted** (raw efficiency isn't comparable across a P4 schedule vs. a G5
  schedule) — sourced from CFBD's SP+ ratings, which are conference-adjusted by construction.
- **Rest differential**: bye week, short week (Thu game), extra rest off a bye.
- **Travel**: distance/time-zone shift.
- **Divisional/conference familiarity**: tighter numbers, trends toward unders.
- **Letdown/lookahead/sandwich spots, revenge games**: only count *with* a real personnel/usage
  signal attached — never on narrative alone.

### F. Market Signals
- Reverse line movement / steam moves (`rlm.py`, reused unmodified from the MLB build — pure
  odds math, not sport-specific).
- Key-number awareness (3, 7, 10) for spread value.

### G. Player Props — Anytime TD Scorer *(NOT built in phase 1 — spec kept for the fast-follow)*
- Red-zone touch share / target share inside the 10 — strongest predictor, volume over efficiency.
- Goal-line role (some backs lose carries at the 5 to a short-yardage specialist).
- Role vacated by injury (ties to category A).
- Run-funnel game script concentrating goal-line carries on the lead back (ties to category C).
- Opponent red-zone defense rank.
- TD regression spots (volume without a TD over 2–3 games).
- Game-script ceiling / garbage-time discount for expected blowouts.

---

## 3. Bet-Type / Market Mapping

| Market | Primary drivers | Secondary drivers |
|---|---|---|
| **Spread** | Mismatches (D), injuries (A), SOS/situational (E) | Weather (B), market (F) |
| **Total (O/U)** | Weather (B), run/pass environment fit (C) | Matchup pace/efficiency (D), skill-position injuries (A) |
| **Moneyline** | Same as spread, injuries (A) and situational (E) weighted higher | Market (F), especially RLM on dog MLs |

`model_football.py` scores each market independently per candidate game — a spread edge does
not automatically imply a total edge; they can point opposite directions.

**RLM check applies to every market.** Before a pick is marked CONFIRMED, it's checked against
`rlm.py`'s read of that line. RLM moving *with* the pick can itself be one of the 2+ stacked
categories; RLM moving *against* the pick doesn't kill it outright, but downgrades
CONFIRMED → **LEAN** until the conflict resolves.

---

## 4. Staking

Same framework as the MLB model (`model.py`'s `american_to_stake`/`cap_rule`, reused
unmodified — pure odds math):
- **Underdog (plus money):** flat **1u**.
- **Favorite −150 or shorter:** risk to win 1u. May stand alone.
- **Favorite harder than −150:** never straight — must pair with another −150+ favorite in a
  parlay.
- **CONFIRMED** (2+ stacked categories) gets standard sizing.
- **LEAN** (CONFIRMED but RLM conflicts) and **NOTE** (exactly 1 category fired) are
  informational only — never staked.

Anytime-TD props: not staked in phase 1 (not built yet — see Section 2G).

---

## 5. Module Map (this repo, phase 1)

| File | Role |
|---|---|
| `model_football.py` | Scoring engine — categories A–F, sport param (`nfl`/`cfb`), per-market weighting, CONFIRMED/LEAN/NOTE/PASS gate |
| `fetch_nfl.py` | NFL schedule/venue/rest (nflverse `games.csv`) + official injury report (nflverse `injuries_<year>.csv`) |
| `fetch_cfb.py` | CFB schedule/venues/SP+ ratings (CollegeFootballData API) |
| `fetch_weather.py` | Reused unmodified from the MLB build (NWS, sport-agnostic) |
| `fetch_odds_football.py` | Spreads/totals/moneylines, both sports (The Odds API) |
| `stadiums_football.py` | Static NFL stadium lat/lon/roof table (CFB venues come from CFBD directly) |
| `rlm.py` | Reused unmodified from the MLB build (pure odds math) |
| `scan_nfl.py` | Weekly-cycle orchestrator |
| `scan_cfb.py` | Daily-per-game-day orchestrator |
| `grade_football.py` | Nightly-ish settlement → `ledger_football.json` |
| `notify.py` | Reused unmodified from the MLB build; football uses its own `NTFY_TOPIC_FOOTBALL` secret so picks land in a separate ntfy feed from baseball. Discord is intentionally not wired up for football yet (ntfy only). |

## 6. Cadence

**NFL** (weekly cycle, `scan_nfl.py`):
- Tue/Wed: injury reports firm up, first-pass scan.
- Thu: separate mini-scan for TNF (short-week signal weighted up).
- Fri: final practice report confirms/kills injury-based edges.
- Sat evening: lock the Sunday slate.
- Mon: separate scan for MNF.

**CFB** (`scan_cfb.py`) — full slates land Tue–Sat, so this runs on a per-game-day basis, not
weekly:
- Standalone Tue/Wed games get their own same-day scan.
- Thu/Fri games get their own mini-scans.
- Sat morning: lock the main slate. Large game count → the 2+ stack requirement matters more
  here to avoid overextending across 40+ games.

## 7. Where CFB Diverges from NFL Logic

- Injury reporting is opaque (see 2A) — no league-mandated report.
- Roster depth is a bigger variable (85-scholarship limit + transfer portal churn).
- SOS spread is much wider — always conference-adjusted (SP+), never raw efficiency.
- Blowout risk changes model use — talent gaps are larger, spreads run wider; garbage-time
  distortion is a bigger factor than in NFL.
- Crowd/road-environment effects are larger than the equivalent NFL road game.
- Weather physics are identical — Section 2B applies unmodified to both sports.

## 8. Notification Format

Mirrors the MLB build's notification structure (ntfy only for football, see Section 5), sport- and market-tagged:
```
[NFL] Team A @ Team B — Spread
Edge: [stacked categories, e.g. "QB out + wind 18mph + run-funnel matchup"]
Confidence: CONFIRMED / LEAN / NOTE
Stake: Xu
```
```
[CFB] Team A @ Team B — Moneyline
Edge: [stacked categories, e.g. "backup QB + true road hostile environment + RLM toward dog"]
Confidence: CONFIRMED / LEAN / NOTE
Stake: Xu
```
