# Unified Betting Model — Canonical Logic Source
_Merged from "Learning Model" + "Basic Model". This is the single source of truth._
_Account: JT111 (play610). Ledgers tracked separately per book._

## 1. Staking (applies to every book)
- **Underdog (plus money):** risk flat **1u**.
- **Favorite within −150 (i.e. −150 or shorter, e.g. −135, −120):** risk **to win 1u**. May stand alone as a single.
- **Favorite harder than −150 (e.g. −160+):** NEVER bet straight/alone. Must be combined in a
  moneyline parlay with at least one other −150-or-harder favorite.
- **Override exceptions** (e.g. a lone heavy fav) are allowed but must be **logged as an exception
  against a named precedent** (Berrettini −155 lost; Scheffler −155 logged). Overrides do NOT change policy.

## 2. Card size
- Normal: **3–5 plays** per multi-game slate.
- Expandable beyond 5 only when genuine edges exist. No forcing plays to fill a card.

## 3. MLB
- Core: **confirmed-legit arms** vs **confirmed mirages** using ERA vs xERA / FIP / xFIP / SIERA / xwOBA.
- **Legit arms (back the side):** Misiorowski, Schlittler, C. Sánchez, Sale, Skenes, Wheeler, H. Brown,
  Ryan, Rasmussen, Mize, Miller, Cease, Harrison, Messick, McClanahan, Ashcraft, N. Martinez, Henderson,
  Detmers, Roupp, Luzardo (high-variance boom/bust), Woodruff.
- **Mirages (fade):** S. Gray (largest xERA gap), E. Rodríguez, T. Melton, Arrighetti, Sugano,
  Wrobleski, Wacha, C. Scott.
- **Reverse mirage** (ugly ERA understates quality — back, don't fade): A. Nola (PHI).
- **Coors Field totals = automatic pass**, both sides, no exceptions. Coors teams playing *away* do NOT trigger it.
- **Tight unders (7 / 7½) keep going over even behind aces** — no auto-firing tight totals; prefer the side.
- **All-Star / Home Run Derby / exhibition = automatic pass** (zero informational edge).

## 4. World Cup 2026 (soccer)
- Primary pattern: **keep-close resilient-dog sides** — back dogs at +½, +1, or pk where draws push.
  (Egypt +1½, Norway +½ x2, Switzerland +½&+1, England +½ all cashed on this logic.)
- **Knockout unders are NOT automatic** — failed repeatedly when both defenses leaky + both attacks high-output.
  Invert to the over/side in those spots.
- **Quiet-favorite lay trap = pass.** Do not lay a rotating/low-motivation favorite
  (France −2, Argentina −2, Spain −1 all correctly passed).
- **Consolation / 3rd-place playoffs = pass** (same logic as All-Star auto-pass; low motivation, rotation).

## 5. Tennis — SEPARATE LEDGER, tracked day-to-day (do not restart analysis each slate)
- **A-play trigger:** higher-ranked player priced as a **plus-money dog on their preferred surface**.
  (Worked: Paolini, Muchova, Tauson. Failed: Alexandrova, Fritz — variance acknowledged.)
- **Fitness verification is MANDATORY before every play.**
- **Retirement-profile name-checks:** Dimitrov (Wimbledon retirement history), Djokovic (age/form).
- Cap: **2–4 cleanest spots per day**, modest sizing, no chasing.
- **Post-Wimbledon low-tier events = automatic pass** until the hard-court swing.
- Same staking as main card (dog 1u flat; fav risk-to-win-1u; cap rule applies).

## 6. Golf (added in Basic Model — ledger status OPEN, not yet formalized)
- **Trigger:** leaderboard-position inversion vs market pricing — market favors a higher-profile
  player who is actually *behind* on the board (name-recognition trap = golf's mirage-fade).
- **Emotional-distraction fade multiplier** (e.g. DeChambeau penalty dispute).
- Only run when a vetted read exists; otherwise pass the book (Learning Model passed golf entirely).
- OPEN QUESTION: promote to a formal 6th ledger, or keep informal.

## 7. UFC
- Leakiest book. **One genuinely clean skill edge, or pass entirely.** No vetted fighter database.

## 8. Standing operational rules
- **play610 account balance is a running total unrelated to the unit ledger** — never analyze or reference it.
- Confirm bookings **explicitly**; a recommendation is not a placed bet.
- Prop-firm / futures rules always pulled from the firm's own official site (unrelated to this model).

## 9. RLM / market overlay (added)
Reverse line movement = the line moving **against** the side taking most public tickets
(a sharp-money footprint). Folded in as a **confirm/conflict overlay on the fundamentals
pick — never a standalone trigger** (preserves "one clean edge or pass").
- **Line movement** (open→current) is tracked automatically from odds snapshots.
- **Public ticket %** has no free feed — supply it optionally in `public.json`; the model
  runs fine without it (movement-only "STEAM" layer).
- Tags on the model's chosen side:
  - **RLM-FOR / STEAM-FOR** — market agrees → confirmation, keep as PLAY.
  - **RLM-AGAINST / STEAM-AGAINST** — market opposes → downgrade PLAY to **REVIEW**
    (still surfaced, flagged "consider pass/reduce" — you decide).
- Thresholds: steam ≥3 prob-points, RLM ≥2 prob-points with public ≥60% (tunable in `rlm.py`).

## 10. Nightly grading & model-performance ledger
- Settles the model's recommended **straight singles** to a units ledger (separate from the
  manual play610 ledger).
- Tracks a **per-RLM-tag breakdown** to test whether the market overlay earns its keep
  (compare STEAM-FOR / RLM-FOR win% and units vs NEUTRAL over time).
- Cap-rule parlay legs are recorded W/L but excluded from units (settled manually).
