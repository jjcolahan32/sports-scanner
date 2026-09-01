# Unattended Card Scanner — NFL + CFB

Companion to `README.md` (MLB). Same philosophy, same deployment pattern (GitHub Actions,
triggered by an external cron service hitting `workflow_dispatch`), separate ledger,
separate ntfy feed. `RULES_FOOTBALL.md` is the canonical logic doc — read that first.

**Phase 1: spreads, totals, moneylines only.** Anytime-TD props are a documented
fast-follow (RULES_FOOTBALL.md Section 2G), not built yet.

## Pieces

| File | Job |
|---|---|
| `RULES_FOOTBALL.md` | Canonical combined logic (single source of truth) |
| `model_football.py` | Rules engine — categories A–F, sport param (`nfl`/`cfb`), CONFIRMED/LEAN/NOTE/PASS gate |
| `fetch_nfl.py` | NFL schedule/venue/rest + official weekly injury report (nflverse, free, no key) |
| `fetch_cfb.py` | CFB schedule/venues/SP+ ratings (CollegeFootballData — needs a free key) |
| `fetch_odds_football.py` | Spreads/totals/moneylines, both sports (The Odds API — same key as MLB) |
| `stadiums_football.py` | Static NFL stadium lat/lon/roof table |
| `fetch_weather.py` | Reused unmodified from the MLB build (NWS, free) |
| `rlm.py` | Reused unmodified from the MLB build (pure odds math) |
| `notify.py` | Reused from the MLB build; football uses its own ntfy topic |
| `scan_nfl.py` | Weekly-cycle orchestrator |
| `scan_cfb.py` | Daily-per-game-day orchestrator |
| `grade_football.py` | Settlement → `ledger_football.json` (separate from the MLB ledger) |
| `.github/workflows/scan_nfl.yml` | NFL scan checkpoints (Tue/Wed/Thu/Fri/Sat/Mon, see below) |
| `.github/workflows/scan_cfb.yml` | CFB scan checkpoints (Tue–Sat, own scan per game-day) |
| `.github/workflows/grade_football.yml` | Grading checkpoints (06:00 / 12:00 ET daily) |

## Setup (do it in Claude Code, same pattern as the MLB build)

1. **Phone app:** if you haven't already (MLB setup covers this), install **ntfy**
   (iOS/Android). Subscribe to a **second, separate** private topic for football — treat
   it like a password, e.g. `jt111-football-9f3k2`. Using a separate topic from MLB's
   keeps the two feeds apart on your phone.
2. **CFB data key:** request a free key at
   [collegefootballdata.com/key](https://collegefootballdata.com/key) — needed for CFB
   schedule/venues/SP+ ratings. NFL needs no key at all (nflverse is open).
3. **Odds key:** reuses your existing `ODDS_API_KEY` from the MLB setup — The Odds API's
   free tier covers NFL and CFB spreads/totals/moneylines too, same key.
4. **Repo secrets:** in the repo → Settings → Secrets and variables → Actions, add
   `CFBD_API_KEY` and `NTFY_TOPIC_FOOTBALL` (`ODDS_API_KEY` already exists from MLB setup).
5. **External cron:** using the same cron-job.org account as MLB, add workflow_dispatch
   triggers hitting these three workflows at (all US Eastern, DST-aware):
   - `scan_nfl.yml` — Tue 10:00, Wed 10:00, Thu 14:00, Fri 16:00, Sat 18:00, Mon 14:00
   - `scan_cfb.yml` — Tue 10:00, Wed 10:00, Thu 14:00, Fri 16:00, Sat 09:00
   - `grade_football.yml` — 06:00 and 12:00, every day
   (These times live in `SCAN_CHECKPOINTS_ET`/`GRADE_CHECKPOINTS_ET` at the top of each
   script — tune there if you want to change the cadence, same as the MLB build.)
6. **Test:** Actions tab → nfl-scanner/cfb-scanner → "Run workflow". Or locally:
   `python selftest_football.py` (needs `ODDS_API_KEY`, `CFBD_API_KEY`,
   `NTFY_TOPIC_FOOTBALL` set in your shell) checks every integration end to end and sends
   a real test push.

## What's different from the MLB build

- **No hand-vetted pitcher-style lists.** Every category signal (injury burden, power
  rating, rest, weather) is computed fresh from live data each scan — there's no
  `LEGIT_ARMS`/`MIRAGES` equivalent to hand-maintain, matchups don't repeat like a
  starting pitcher's season stats do.
- **Three verdict tiers, not two.** CONFIRMED (2+ stacked categories) is staked normally.
  LEAN (CONFIRMED but the market opposes it) and NOTE (exactly one category fired) are
  both sent but never staked — informational only.
- **CFB injuries are opaque.** No official report exists; category A only fires for CFB
  off an optional hand-maintained `public_cfb_injuries.json` (same idea as the MLB
  build's `public.json`) — most CFB games will simply have no injury signal, which is
  honest, not a bug.
- **Discord isn't wired up for football yet** — ntfy only, by design (can add a
  `DISCORD_WEBHOOK_URL_FOOTBALL` channel later the same way the MLB build did, `notify.py`
  and `discord_notify.py` are already generic enough to support it without changes).
- **NFL power ratings are a crude proxy**, not adjusted for opponent strength (a straight
  season scoring-margin average) — CFB's SP+ (from CFBD) is meaningfully more
  sophisticated (conference-adjusted). Worth knowing when reading the "mismatch" reason
  text on a pick.

## Nightly-ish grading

`grade_football.py` settles `card_nfl_*.json`/`card_cfb_*.json` against final scores,
updates `ledger_football.json` (own units, separate from MLB), and pushes a summary to
the football ntfy topic. Idempotent, same as the MLB grader — reruns only settle games
that have since gone final.
