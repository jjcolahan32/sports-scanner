# Unattended Card Scanner — MLB

Scans MLB games on a schedule, grades any game whose probable pitcher is on your
vetted lists, and **texts/pushes the plays to your phone 3–4 hours before first pitch**.
No tabs open, nothing to stay logged into.

## Pieces
| File | Job |
|---|---|
| `RULES.md` | Canonical combined logic (single source of truth) |
| `model.py` | Rules engine — grades a slate |
| `fetch_mlb.py` | Today's games + start times + probable pitchers (MLB StatsAPI, no login) |
| `fetch_odds.py` | Consensus MLB moneylines (The Odds API free tier) |
| `notify.py` | Push to your phone (ntfy.sh, free) |
| `rlm.py` | Reverse-line-movement / steam overlay (confirm vs conflict) |
| `scan.py` | Orchestrator: window filter → match → grade → RLM overlay → dedupe → notify |
| `grade.py` | **Nightly** settlement: finals → W/L → ledgers → push day P&L |
| `.github/workflows/scan.yml` | Runs `scan.py` every 2 hours, 24/7, in the cloud |
| `.github/workflows/grade.yml` | Runs `grade.py` nightly at 08:00 UTC (~04:00 ET) |

## How the timing works (no day-of-week guessing)
Each game carries its real start time. A game is flagged when it starts within
`LEAD_HOURS` (default 4) **and** its probable pitcher (posted ~4h out) is vetted.
The cron runs every 2h, so each game is caught once its pitcher posts; a per-day
dedupe file (`state.json`) guarantees no game alerts twice, and it self-resets daily.

- **Back** a legit / reverse-mirage arm → bets HIS team's ML.
- **Fade** a mirage arm → bets the OPPONENT's ML.
- Coors totals, All-Star/exhibition games, and out-of-window games are skipped.
- Cap rule fires: any −150+ favorite is flagged to parlay, never sent as a lone single.

## Setup (one time, ~15 min — do it in Claude Code)
1. **Phone app:** install **ntfy** (iOS/Android). Subscribe to a private topic name
   you invent — treat it like a password (e.g. `jt111-mlb-9f3k2`). Unguessable matters:
   anyone who knows the topic can push to you.
2. **Odds key:** grab a free key at the-odds-api.com (free tier covers MLB moneyline).
3. **Repo:** push this folder to a private GitHub repo.
4. **Secrets:** in the repo → Settings → Secrets and variables → Actions, add
   `ODDS_API_KEY` and `NTFY_TOPIC`.
5. **Test:** Actions tab → card-scanner → "Run workflow". Watch for a push.
   Or locally: `NTFY_TOPIC=... python notify.py` should ping your phone.

That's it. From then on it runs itself every 2 hours.

## RLM / market overlay
On top of the fundamentals pick, the scanner reads the market:
- It **snapshots opening lines** (`opens.json`, auto-reset daily) and measures how far
  each side has moved by scan time.
- **Movement-only** (default): a big move toward your side tags **STEAM-FOR** (confirmation);
  a big move off it tags **STEAM-AGAINST** and downgrades the play to **REVIEW**.
- **True RLM** kicks in only if you supply public ticket % — there's no free feed, so read it
  off Action Network / VSiN / Covers and drop it into `public.json` (see `public.example.json`,
  keyed by MLB `game_pk`). Heavy public on your side + line drifting off it = **RLM-AGAINST** → REVIEW.
- Conflicts are never silently dropped — they're pushed to you flagged, and you decide.
- Tune thresholds at the top of `rlm.py`.

## What stays manual (by design)
- **Placing bets.** The scanner never logs into play610 and never places a wager —
  it tells you what qualifies; you place it and confirm the exact line yourself.
- Consensus odds flag dog/fav + rough price; the real play610 number is what you book on.

## Extending
- Add tennis/soccer/golf: write a `fetch_*` for each and add rows to the slate in `scan.py`.
  Tennis has no free probable-pitcher-equivalent auto-feed and needs fitness checks, so it
  stays a manual/assisted book for now.
- Change lead time: set `LEAD_HOURS` in the workflow env.
- Change cadence: edit the cron in `scan.yml` (e.g. `0 */1 * * *` for hourly).

## Nightly grading
`grade.py` runs once a night (08:00 UTC job). It:
1. Reads every `card_*.json` the scanner wrote and finds ungraded plays.
2. Pulls finals from the MLB API and settles each moneyline W/L.
3. Updates `ledger.json`: MLB model units, W-L record, a **per-RLM-tag breakdown**
   (so you can see whether STEAM-FOR / RLM-FOR plays actually beat NEUTRAL ones),
   and a rolling history.
4. Pushes the day's summary to your phone (record, day P&L, running ledger, tag table).

It's **idempotent** — reruns only settle games that have since gone Final, nothing double-counts.

**What's graded, honestly:**
- Straight singles (dogs, favs ≤ −150) → settled to units. This is a *model-performance*
  ledger, separate from your manual play610 unit ledger.
- Cap-rule parlay legs (favs harder than −150) → W/L tracked for info, **not** added to units
  (you build those parlays by hand, so their real payout is yours to settle).
- REVIEW plays are graded and bucketed by tag, so you can see how the market-opposed spots did.
