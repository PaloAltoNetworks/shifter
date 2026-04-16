# Operation NORTHSTORM — Event Data Report

_Generated 2026-04-16T20:18:46.996758+00:00_

## Top-line numbers

- **110** participants enrolled; **61** made at least one submission; **60** scored.
- **1328** total solves across **55** visible challenges.
- **5728** total submissions: **1328** correct, **2890** incorrect, **1510** rate-limited (_26.4% of all submissions_).
- Top score: **4850**. Mean among active: **1782.0**. Median (all): **300**.

## Headline findings

**Submission-loop discoverability explains most of the variance.** Operators split into two Claude-assisted workflows: (8) who copy-pasted Claude's output into the CTFd browser tab, and (13) who figured out how to let Claude hit the submission endpoint directly. **11 operators visibly crossed over mid-event** (early-session burst density under 10%, late-session burst density above 20%). Two of the four ceiling-tied operators are in this group — they started slow and sped up after discovering the Claude-drives-submission workflow. The two clusters are not two Claude styles; they are two operator integrations.

**The ceiling is structural.** 4 operators tied at the top score ($4850). They did not solve similar challenges — they solved the **exact same 49 challenges**, every one of them. The ceiling is everything except M5 Bunker.

**Two bottlenecks.** M3 Lab: 26 attempted, 9 got any solve, 5 cleared. Hard content even once the pivot lands. M5 Bunker: 7 attempted, **0 solved anything** across 6 challenges. Either the blackout→splice mechanic didn't fully open the route, or the OT protocol work is too far outside most comfort zones for a 4-hour window.

**Attendance was the real gate.** 61/110 enrolled operators submitted anything. For an event whose design assumption was "everyone has Claude," the loss in the onboarding funnel mattered more than any content tuning.

**Platform rate-limits.** CTFd threw **1510 rate-limit responses** (26% of all submissions) concentrated in the Claude-drives-submission cluster. Default CTFd rate-limit config treats a human typing and an AI looping the same — that's a platform-tuning gap for agentic events.

**Hint 2 = answer on hard content.** 8 challenges show +80% or greater solve-rate lift for hint-unlockers. By design, but economically it means paying for the answer, not paying for a nudge.

## Difficulty calibration

| Designated | N | Mean | Median | Min | Max |
|---|---|---|---|---|---|
| easy | 19 | 32.6% | 32.7% | 6.4% | 53.6% |
| medium | 24 | 21.2% | 27.3% | 0.0% | 35.4% |
| hard | 8 | 8.0% | 7.3% | 0.0% | 17.3% |
| expert | 4 | 3.4% | 2.3% | 0.0% | 9.1% |

Solve rate falls monotonically with designated difficulty. Calibration held.

## Mission funnel (attempted → touched → cleared)

| Mission | Challenges | Attempted | Touched (≥1 solve) | Fully cleared | Attempted-but-0-solves |
|---|---|---|---|---|---|
| M0 | 1 | 60 | 57 | 57 | 3 |
| M1 | 6 | 59 | 59 | 20 | 0 |
| M2 | 11 | 50 | 47 | 8 | 3 |
| M3 | 12 | 26 | 9 | 5 | 17 |
| M4 | 3 | 25 | 19 | 10 | 6 |
| M5 | 6 | 7 | 0 | 0 | 7 |
| M6 | 4 | 41 | 40 | 32 | 1 |
| M7 | 4 | 36 | 35 | 31 | 1 |
| M8 | 4 | 34 | 34 | 32 | 0 |
| M9 | 4 | 33 | 32 | 29 | 1 |

The `Attempted-but-0-solves` column shows frustration pockets. M5 (Bunker) is pure frustration: lots of attempts, zero solves.

## Pareto share

- Top 5% of active operators: **13%** of points, **11%** of solves.
- Top 10%: **26%** of points, **22%** of solves.
- Top 25%: **53%** of points, **46%** of solves.

Active participants: **61** of 110 enrolled.

## Workflow membership (derived from cluster → operator workflow)

| Cluster | Workflow interpretation | Count |
|---|---|---|
| inactive | never engaged | 49 |
| mixed | mixed / transitional | 27 |
| burst-low-accuracy | Claude drives submission | 13 |
| manual-struggling | manual / unassisted | 11 |
| high-accuracy-slow | human-in-loop (copy-paste from Claude) | 8 |
| low-engagement | barely engaged | 1 |
| engaged-unsuccessful | engaged but stuck | 1 |

### Operators who discovered Claude-submits mid-event

Bimodal burst-density signature: quiet early, bursty late.

| Operator | Points | Solves | Burst density early | Burst density late | Cluster |
|---|---|---|---|---|---|
| op024 | 4850 | 49 | 13% | 46% | burst-low-accuracy |
| op095 | 4850 | 49 | 26% | 89% | burst-low-accuracy |
| op007 | 4500 | 47 | 21% | 86% | burst-low-accuracy |
| op098 | 3850 | 42 | 8% | 20% | manual-struggling |
| op044 | 2500 | 31 | 0% | 35% | high-accuracy-slow |
| op037 | 2100 | 28 | 0% | 29% | high-accuracy-slow |
| op076 | 1400 | 17 | 0% | 21% | mixed |
| op084 | 750 | 11 | 0% | 17% | mixed |
| op003 | 450 | 8 | 11% | 25% | mixed |
| op101 | 400 | 8 | 6% | 18% | manual-struggling |
| op034 | 350 | 7 | 0% | 29% | mixed |

Rules:
- `likely-agentic` — ≥3 solves, ≥70% success, ≥20% of gaps <2s
- `burst-low-accuracy` — ≥20% burst density but <70% success (AI spraying)
- `high-accuracy-slow` — ≥70% success, <20% burst density (disciplined manual or light AI)
- `manual-struggling` — <35% success, <15% burst density
- `mixed` — everything in between
- `engaged-unsuccessful` — submitted but zero solves
- `low-engagement` — fewer than 3 solves
- `inactive` — zero submissions

### Rate-limit pressure by cluster

| Cluster | N | Mean RL ratio | Median RL ratio |
|---|---|---|---|
| burst-low-accuracy | 13 | 30.2% | 22.5% |
| manual-struggling | 11 | 2.4% | 0.0% |
| mixed | 27 | 0.4% | 0.0% |
| high-accuracy-slow | 8 | 0.0% | 0.0% |
| low-engagement | 1 | 0.0% | 0.0% |
| engaged-unsuccessful | 1 | 0.0% | 0.0% |

If agentic operators drive platform rate-limits, `likely-agentic` and `burst-low-accuracy` should be at the top. They are. This is the CTFd platform cost of giving participants Claude.

## Hint ROI (operator POV)

- 41 operators bought hints.
- 35 ended net-positive (earned more on hint-unlocked challenges than they spent).
- 6 ended net-negative.
- Total community hint spend: **5385 pts**. Total earned on hint-unlocked challenges: **12000 pts**. Net: **+6615 pts**.
- Wasted hints (unlocked but never solved): **80**.

## Top 20 scorers

| # | Label | Points | Solves | Real attempts | Success | RL ratio | Hints | Arrival | Cluster |
|---|---|---|---|---|---|---|---|---|---|
| 1 | op017 | 4850 | 49 | 269 | 18% | 14% | 27 | 59m | burst-low-accuracy |
| 2 | op024 | 4850 | 49 | 109 | 45% | 0% | 5 | 56m | burst-low-accuracy |
| 3 | op095 | 4850 | 49 | 221 | 22% | 22% | 0 | 61m | burst-low-accuracy |
| 4 | op107 | 4850 | 49 | 327 | 15% | 56% | 32 | 78m | burst-low-accuracy |
| 5 | op001 | 4800 | 48 | 211 | 23% | 7% | 5 | 80m | burst-low-accuracy |
| 6 | op007 | 4500 | 47 | 153 | 31% | 38% | 2 | 89m | burst-low-accuracy |
| 7 | op082 | 4100 | 43 | 223 | 19% | 5% | 7 | 56m | manual-struggling |
| 8 | op098 | 3850 | 42 | 220 | 19% | 17% | 1 | 79m | manual-struggling |
| 9 | op038 | 3400 | 37 | 261 | 14% | 30% | 2 | 65m | burst-low-accuracy |
| 10 | op106 | 3350 | 36 | 51 | 71% | 0% | 12 | 105m | high-accuracy-slow |
| 11 | op049 | 3100 | 36 | 106 | 34% | 2% | 0 | 77m | manual-struggling |
| 12 | op070 | 3000 | 36 | 103 | 35% | 75% | 4 | 56m | burst-low-accuracy |
| 13 | op047 | 2750 | 33 | 57 | 58% | 0% | 1 | 76m | mixed |
| 14 | op004 | 2600 | 32 | 41 | 78% | 0% | 4 | 59m | high-accuracy-slow |
| 15 | op041 | 2600 | 31 | 67 | 46% | 4% | 4 | 48m | mixed |
| 16 | op014 | 2550 | 32 | 85 | 38% | 2% | 3 | 56m | mixed |
| 17 | op044 | 2500 | 31 | 40 | 78% | 0% | 1 | 76m | high-accuracy-slow |
| 18 | op023 | 2400 | 27 | 65 | 42% | 77% | 0 | 95m | burst-low-accuracy |
| 19 | op036 | 2200 | 29 | 61 | 48% | 0% | 4 | 80m | mixed |
| 20 | op002 | 2100 | 28 | 58 | 48% | 74% | 3 | 128m | burst-low-accuracy |

## Hardest challenges that at least ONE person solved (by conditional rate: of people who attempted, how few solved)

| Challenge | Mission | Diff | Attempters | Solvers | Conditional rate | Median attempts/solver | Median min-to-solve |
|---|---|---|---|---|---|---|---|
| What Git Remembers | M3 | medium | 21 | 6 | 28.6% | 4.0 | 200 |
| Project Hints | M2 | easy | 38 | 12 | 31.6% | 6.0 | 124 |
| After Hours | M3 | medium | 18 | 6 | 33.3% | 2.5 | 42 |
| Old Defaults | M3 | easy | 20 | 7 | 35.0% | 4 | 67 |
| Balance Point | M3 | medium | 17 | 6 | 35.3% | 3.0 | 39 |
| Full Run | M3 | expert | 14 | 5 | 35.7% | 5 | 207 |
| Password Reuse | M2 | easy | 33 | 12 | 36.4% | 2.5 | 43 |
| MIDNIGHT-7 | M3 | medium | 17 | 7 | 41.2% | 2 | 58 |
| What Was Erased | M3 | hard | 17 | 7 | 41.2% | 2 | 164 |
| Follow the Money | M1 | medium | 48 | 20 | 41.7% | 5.0 | 142 |

## Grind challenges (median attempts-per-solver among those who solved)

| Challenge | Mission | Diff | Median attempts | Solvers |
|---|---|---|---|---|
| Project Hints | M2 | easy | 6.0 | 12 |
| Follow the Money | M1 | medium | 5.0 | 20 |
| Full Run | M3 | expert | 5 | 5 |
| Lateral Movement | M2 | medium | 4 | 19 |
| Old Defaults | M3 | easy | 4 | 7 |
| Compartment A | M3 | easy | 4 | 9 |
| What Git Remembers | M3 | medium | 4.0 | 6 |
| Unreliable Guard | M2 | medium | 3.0 | 16 |
| Lights Out | M4 | expert | 3.0 | 10 |
| Heavy Delivery | M3 | easy | 3 | 9 |

## Zero-solve challenges

All 6 belong to **M5 Bunker**. Combined 624 submissions across these from 34 participant-attempts.

| Challenge | Difficulty | Attempters | Total submissions | Rate-limited |
|---|---|---|---|---|
| Underground Signals | medium | 7 | 109 | 23 |
| First Motion | hard | 6 | 88 | 26 |
| Walking Pattern | hard | 6 | 80 | 28 |
| Response Window | hard | 5 | 79 | 29 |
| Control Channel | expert | 5 | 81 | 42 |
| Full Override | expert | 5 | 187 | 67 |

## Arrival pattern

Of 61 active operators, first-submission offset from event start:

| Offset (minutes) | Participants |
|---|---|
| 45–60 | 16 |
| 60–75 | 11 |
| 75–90 | 21 |
| 90–105 | 3 |
| 105–120 | 5 |
| 120–135 | 3 |
| 150–165 | 1 |
| 180–195 | 1 |

## Order of attack — first-solve by mission

What was the first challenge each operator solved?

| Mission | Operators starting here |
|---|---|
| M0 | 53 |
| M1 | 7 |
