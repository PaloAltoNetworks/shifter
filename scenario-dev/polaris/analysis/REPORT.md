# Operation NORTHSTORM — Event Data Report

_Generated 2026-04-17T02:07:23.975479+00:00_

## Top-line numbers

- **61** operators participated (submitted at least once); **60** scored.
- **1391** total solves across **55** visible challenges.
- **7432** total submissions: **1391** correct, **3873** incorrect, **2168** rate-limited (_29.2% of all submissions_).
- Top score: **4850**. Mean among active: **1898.4**. Median (active): **1700**.

## The headline finding (revised with post-event infra analysis)

**M5 Bunker's zero-solve rate was a deployment bug, not design difficulty or skill gap.** The splice-watcher systemd unit on every polaris-vm was configured with a container name (`a5-scada-generator`) that did not match what was actually baked (`a5-scada`). The watcher silently failed every 10 seconds for ~30 hours. Every operator who tripped the A5 meltdown (by solving M4 — Lights Out) SHOULD have had `a14-kali` automatically attached to `build_splice-link` — none did. The bunker was unreachable for the entire event window.

**The data reveals operators who knew the answer but couldn't send it.** 3 operators — op107, op7, op17 — submitted the **correct override code** `7741-MN07-AL42` directly to the CTFd endpoint, having correctly assembled it from three separate range artifacts (M1 A0 registration number, M3 A6 MIDNIGHT-7 simulation ID, M3 A8 assembly-log metadata). They were submitting to CTFd because they had no network route to run `override 7741-MN07-AL42` on the brain (A13:9100) — which is the real mechanic. Once the splice-watcher was patched mid-event, the splice worked correctly for any fresh meltdown. Twelve of the operators who had done the M4 work got a manual splice for a 24h extension to finish.

## Other findings

**Stuck-signature detection could have caught the infra failure live.** The signature — high submission rate + internally-consistent near-answers + zero solves, concentrated on one challenge — is detectable with a trivial heuristic (per-challenge near-answer regex, alert when ≥2 operators ≥5 near-answers with 0 solves). We had the signal throughout; we weren't watching for it. Build this into the next event's dashboard.

**Submission-loop discoverability explains most of the score variance.** Operators split into two Claude-assisted workflows: (7) who copy-pasted Claude's output into the CTFd browser tab, and (15) who figured out how to let Claude hit the submission endpoint directly. **10 operators visibly crossed over mid-event** (early-session burst density under 10%, late-session burst density above 20%). Two of the four ceiling-tied operators are in this group. The clusters are not two Claude modes; they are two operator integrations.

**The ceiling is structural.** 7 operators tied at the top score ($4850). They all solved the **exact same 49 challenges** — everything except M5 Bunker. Now we know why: the splice-watcher bug capped them there.

**M3 Lab was genuine difficulty.** M3: 27 attempted, 11 got any solve, 7 cleared. Unlike M5, operators who reached M3 ran out of time and technique, not infrastructure. This is what intended-difficulty looks like in the data: plenty of attempts, some solves, clear gradient.

**Platform rate-limits.** CTFd threw **2168 rate-limit responses** (~29% of all submissions) concentrated in the Claude-drives-submission cluster. Default CTFd rate-limit config treats a human typing and an AI looping the same — a platform-tuning gap for agentic events.

**Hint 2 = answer on hard content.** 9 challenges show +80% or greater solve-rate lift for hint-unlockers. Economically: paying for the answer, not paying for a nudge.

## Stuck-signature detection (Full Override)

Per-operator breakdown of Full Override (challenge 36) submissions. `HAS_ANSWER_STUCK` means the operator submitted the exact correct override code to CTFd but never solved the challenge — the unambiguous signature that they knew the answer but couldn't execute the mechanic. `KNOWS_PIECES_STUCK` means they assembled all three pieces (7741, MN07, AL42) in some ordering but never landed on the correct permutation at CTFd (which still wouldn't have worked — the code had to run against the brain).

| Operator | Category | Total subs | Exact code | 3-piece variants | 2-piece variants | FLAG{} guesses |
|---|---|---:|---:|---:|---:|---:|
| op107 | HAS_ANSWER_STUCK | 804 | 20 | 71 | 20 | 115 |
| op007 | HAS_ANSWER_STUCK | 79 | 1 | 40 | 0 | 72 |
| op017 | HAS_ANSWER_STUCK | 22 | 2 | 7 | 2 | 6 |
| op095 | BRUTE_SPRAYING | 21 | 0 | 0 | 0 | 21 |
| op001 | ATTEMPTING | 8 | 0 | 0 | 0 | 8 |
| op022 | ATTEMPTING | 8 | 0 | 0 | 0 | 8 |

## Related work / landscape (as of April 2026)

Context for the findings above: how our results sit next to what's publicly known about AI-assisted CTFs.

### Format scarcity

I could not find a published analog at this scale — ~110 human operators, each issued a preconfigured frontier agent inside an isolated range, running against a difficulty-calibrated IT+OT challenge set. Related but distinct formats exist:

- **AI-vs-human CTFs** — autonomous agent teams competing against humans. E.g., [HTB × Palisade Research (Jan 2025)](https://www.hackthebox.com/blog/ai-vs-human-ctf-hack-the-box-results): 8 agent teams vs 153 human teams. Different question.
- **AI-as-copilot pilots** — [HTB "Attack of the Agents" (June 2025)](https://www.hackthebox.com/blog/attack-of-the-agents-ctf) — same format as ours but much smaller scale.
- **Agent-building competitions** — [CSAW Agentic Automated CTF (2025)](https://www.csaw.io/agentic-automated-ctf): participants build the agent rather than play with it.
- **BYO-AI** — tolerated at BSides / picoCTF / etc., but no uniform provisioning, not measurement-comparable.

### What published data exists on AI × CTF solve rates

- **[DARPA AIxCC final](https://www.darpa.mil/news/2025/aixcc-results)** (DEF CON 33, Aug 2025) — autonomous cyber reasoning systems. Agent capability, not human-plus-agent.
- **[Cybench](https://arxiv.org/abs/2408.08926)** (Stanford CRFM, NeurIPS 2024, arXiv:2408.08926) — agent first-solve-time correlates with human difficulty; first-solve-time cliff above ~11 minutes. Closest published analog to our difficulty-gradient observation.
- **[NYU CTF Bench](https://arxiv.org/abs/2406.05590)** (NeurIPS 2024), **EnIGMA**, **CTF-Dojo**, **CAI** — all agent-capability benchmarks.
- **[UK AISI Claude "Mythos Preview" eval](https://www.aisi.gov.uk/blog/our-evaluation-of-claude-mythos-previews-cyber-capabilities)** (Apr 2026): 73% on expert cyber tasks; Claude at top 3% on PicoCTF 2025.
- **Suzu Labs — "Death of the CTF"** (Mar 2026): root-blood times on HTB declining ~16%/yr post-LLM, with 27% (Hard) → 67% (Insane) compression across difficulty tiers. Measures the time dimension of agent impact.

### Is our "monotonic solve-rate decline despite AI access" result novel?

Direction is expected — Cybench and Suzu Labs both show agents still hit a difficulty ceiling. What's plausibly new in this data:

- **Scale in a human population**: 61 active operators each with an agent, not agent-only benchmarks or single-operator pilots.
- **Clean calibration (easy/medium/hard/expert) surviving universal AI access**: this is a stronger claim than "agents have a ceiling" — it says the designers' labels still correctly sorted the content under AI assistance.
- **IT + OT mix** (SCADA/Modbus + custom binary protocol). OT content is near-absent from published LLM-CTF literature, making our M9 and M5 data the most novel slice.

### Honest gaps

- Can't rule out unpublished industry events running similar formats. "Unprecedented" here = "I couldn't find one published."
- Causal claims about *why* solve rates fell (what makes expert harder than hard for AI-assisted teams) aren't in the data. We see the what, not the why.
- The M5 Bunker confound — the hardest mission was also the broken one. The solve rate on M5 tells us nothing about its actual difficulty.

### Mission-level frustration index

Per-operator × per-mission: ≥20 submissions, 0 solves in that mission. Concentration on a single mission — especially M5 in this table — is the coarse-grained version of the stuck signature.

| Operator | Mission | Submissions | Solves |
|---|---|---:|---:|
| op107 | M5 | 765 | 0 |
| op007 | M5 | 135 | 0 |
| op001 | M5 | 107 | 0 |
| op095 | M5 | 103 | 0 |
| op038 | M3 | 95 | 0 |
| op064 | M3 | 50 | 0 |
| op017 | M5 | 48 | 0 |
| op022 | M5 | 41 | 0 |
| op049 | M3 | 31 | 0 |
| op014 | M3 | 24 | 0 |

## Difficulty calibration

| Designated | N | Mean | Median | Min | Max |
|---|---|---|---|---|---|
| easy | 19 | 33.6% | 33.6% | 9.1% | 53.6% |
| medium | 24 | 22.4% | 27.3% | 0.0% | 36.4% |
| hard | 8 | 9.1% | 8.6% | 0.0% | 20.0% |
| expert | 4 | 4.3% | 3.2% | 0.0% | 10.9% |

Solve rate falls monotonically with designated difficulty. Calibration held.

## Mission funnel (attempted → touched → cleared)

| Mission | Challenges | Attempted | Touched (≥1 solve) | Fully cleared | Attempted-but-0-solves |
|---|---|---|---|---|---|
| M0 | 1 | 60 | 57 | 57 | 3 |
| M1 | 6 | 59 | 59 | 21 | 0 |
| M2 | 11 | 51 | 48 | 10 | 3 |
| M3 | 12 | 27 | 11 | 7 | 16 |
| M4 | 3 | 28 | 22 | 12 | 6 |
| M5 | 6 | 10 | 0 | 0 | 10 |
| M6 | 4 | 42 | 41 | 33 | 1 |
| M7 | 4 | 37 | 36 | 32 | 1 |
| M8 | 4 | 35 | 35 | 33 | 0 |
| M9 | 4 | 33 | 32 | 29 | 1 |

The `Attempted-but-0-solves` column shows frustration pockets. M5 (Bunker) is pure frustration: lots of attempts, zero solves.

## Pareto share

- Top 5% of active operators: **13%** of points, **11%** of solves.
- Top 10%: **25%** of points, **21%** of solves.
- Top 25%: **54%** of points, **47%** of solves.

Active participants: **61** of 110 enrolled.

## Workflow membership (derived from cluster → operator workflow)

| Cluster | Workflow interpretation | Count |
|---|---|---|
| inactive | never engaged | 49 |
| mixed | mixed / transitional | 26 |
| burst-low-accuracy | Claude drives submission | 15 |
| manual-struggling | manual / unassisted | 11 |
| high-accuracy-slow | human-in-loop (copy-paste from Claude) | 7 |
| low-engagement | barely engaged | 1 |
| engaged-unsuccessful | engaged but stuck | 1 |

### Operators who discovered Claude-submits mid-event

Bimodal burst-density signature: quiet early, bursty late.

| Operator | Points | Solves | Burst density early | Burst density late | Cluster |
|---|---|---|---|---|---|
| op024 | 4850 | 49 | 13% | 46% | burst-low-accuracy |
| op095 | 4850 | 49 | 29% | 92% | burst-low-accuracy |
| op044 | 4100 | 44 | 37% | 86% | burst-low-accuracy |
| op098 | 3850 | 42 | 8% | 20% | manual-struggling |
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
| burst-low-accuracy | 15 | 29.3% | 28.7% |
| manual-struggling | 11 | 2.6% | 1.4% |
| mixed | 26 | 0.4% | 0.0% |
| high-accuracy-slow | 7 | 0.0% | 0.0% |
| low-engagement | 1 | 0.0% | 0.0% |
| engaged-unsuccessful | 1 | 0.0% | 0.0% |

If agentic operators drive platform rate-limits, `likely-agentic` and `burst-low-accuracy` should be at the top. They are. This is the CTFd platform cost of giving participants Claude.

## Hint ROI (operator POV)

- 41 operators bought hints.
- 33 ended net-positive (earned more on hint-unlocked challenges than they spent).
- 7 ended net-negative.
- Total community hint spend: **6910 pts**. Total earned on hint-unlocked challenges: **13350 pts**. Net: **+6440 pts**.
- Wasted hints (unlocked but never solved): **95**.

## Top 20 scorers

| # | Label | Points | Solves | Real attempts | Success | RL ratio | Hints | Arrival | Cluster |
|---|---|---|---|---|---|---|---|---|---|
| 1 | op001 | 4850 | 49 | 289 | 17% | 6% | 6 | 80m | burst-low-accuracy |
| 2 | op007 | 4850 | 49 | 274 | 18% | 34% | 19 | 89m | burst-low-accuracy |
| 3 | op017 | 4850 | 49 | 269 | 18% | 14% | 27 | 59m | burst-low-accuracy |
| 4 | op024 | 4850 | 49 | 109 | 45% | 0% | 5 | 56m | burst-low-accuracy |
| 5 | op082 | 4850 | 49 | 248 | 20% | 5% | 20 | 56m | manual-struggling |
| 6 | op095 | 4850 | 49 | 243 | 20% | 21% | 0 | 61m | burst-low-accuracy |
| 7 | op107 | 4850 | 49 | 876 | 6% | 51% | 34 | 78m | burst-low-accuracy |
| 8 | op022 | 4400 | 46 | 188 | 24% | 30% | 0 | 120m | burst-low-accuracy |
| 9 | op044 | 4100 | 44 | 102 | 43% | 29% | 1 | 76m | burst-low-accuracy |
| 10 | op098 | 3850 | 42 | 220 | 19% | 17% | 1 | 79m | manual-struggling |
| 11 | op038 | 3400 | 37 | 261 | 14% | 30% | 2 | 65m | burst-low-accuracy |
| 12 | op106 | 3350 | 36 | 51 | 71% | 0% | 12 | 105m | high-accuracy-slow |
| 13 | op049 | 3100 | 36 | 106 | 34% | 2% | 0 | 77m | manual-struggling |
| 14 | op014 | 3050 | 35 | 107 | 33% | 2% | 3 | 56m | manual-struggling |
| 15 | op070 | 3000 | 36 | 103 | 35% | 75% | 4 | 56m | burst-low-accuracy |
| 16 | op047 | 2750 | 33 | 57 | 58% | 0% | 1 | 76m | mixed |
| 17 | op004 | 2600 | 32 | 41 | 78% | 0% | 4 | 59m | high-accuracy-slow |
| 18 | op041 | 2600 | 31 | 67 | 46% | 4% | 4 | 48m | mixed |
| 19 | op023 | 2400 | 27 | 65 | 42% | 77% | 0 | 95m | burst-low-accuracy |
| 20 | op036 | 2200 | 29 | 61 | 48% | 0% | 4 | 80m | mixed |

## Hardest challenges that at least ONE person solved (by conditional rate: of people who attempted, how few solved)

| Challenge | Mission | Diff | Attempters | Solvers | Conditional rate | Median attempts/solver | Median min-to-solve |
|---|---|---|---|---|---|---|---|
| What Git Remembers | M3 | medium | 23 | 7 | 30.4% | 4 | 240 |
| Project Hints | M2 | easy | 39 | 14 | 35.9% | 6.0 | 142 |
| Password Reuse | M2 | easy | 35 | 14 | 40.0% | 3.0 | 54 |
| What Was Erased | M3 | hard | 19 | 8 | 42.1% | 2.0 | 160 |
| After Hours | M3 | medium | 21 | 9 | 42.9% | 3 | 57 |
| Follow the Money | M1 | medium | 48 | 21 | 43.8% | 5 | 159 |
| Full Run | M3 | expert | 16 | 7 | 43.8% | 5 | 333 |
| Balance Point | M3 | medium | 20 | 9 | 45.0% | 3 | 120 |
| Old Defaults | M3 | easy | 22 | 10 | 45.5% | 4.0 | 123 |
| The Analyst's Desk | M3 | medium | 23 | 11 | 47.8% | 2 | 54 |

## Grind challenges (median attempts-per-solver among those who solved)

| Challenge | Mission | Diff | Median attempts | Solvers |
|---|---|---|---|---|
| Project Hints | M2 | easy | 6.0 | 14 |
| Follow the Money | M1 | medium | 5 | 21 |
| Full Run | M3 | expert | 5 | 7 |
| Old Defaults | M3 | easy | 4.0 | 10 |
| Compartment A | M3 | easy | 4 | 11 |
| MIDNIGHT-7 | M3 | medium | 4.0 | 10 |
| What Git Remembers | M3 | medium | 4 | 7 |
| Lateral Movement | M2 | medium | 3.5 | 20 |
| Password Reuse | M2 | easy | 3.0 | 14 |
| Unreliable Guard | M2 | medium | 3 | 17 |

## Zero-solve challenges

All 6 belong to **M5 Bunker**. Combined 1865 submissions across these from 43 participant-attempts.

| Challenge | Difficulty | Attempters | Total submissions | Rate-limited |
|---|---|---|---|---|
| Underground Signals | medium | 10 | 247 | 47 |
| First Motion | hard | 8 | 181 | 46 |
| Walking Pattern | hard | 7 | 163 | 50 |
| Response Window | hard | 6 | 165 | 53 |
| Control Channel | expert | 6 | 167 | 75 |
| Full Override | expert | 6 | 942 | 388 |

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
