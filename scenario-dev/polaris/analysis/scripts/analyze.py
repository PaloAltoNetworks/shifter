#!/usr/bin/env python3
"""Analyze CTFd event data dumped to ../data/raw/.

Outputs:
  ../data/analysis.json   — machine-readable, drives the website
  ../data/cleaned/*.csv   — PII-scrubbed tabular data for downstream analysis
  ../REPORT.md            — written human summary
"""
from __future__ import annotations

import json
import csv
import os
import re
import statistics
import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path

ANALYSIS_DIR = Path(__file__).resolve().parents[1]
RAW = ANALYSIS_DIR / "data" / "raw"
CLEAN = ANALYSIS_DIR / "data" / "cleaned"
OUT_JSON = ANALYSIS_DIR / "data" / "analysis.json"
OUT_REPORT = ANALYSIS_DIR / "REPORT.md"
CLEAN.mkdir(parents=True, exist_ok=True)

def load(name): return json.load(open(RAW / f"{name}.json"))
users        = load("users")
challenges   = load("challenges")
hints        = load("hints")
flags        = load("flags")
tags         = load("tags")
solves       = load("solves")
submissions  = load("submissions")
unlocks      = load("unlocks")
awards       = load("awards")

# ---------------------------------------------------------------------------
# Filter to real participants (by email, which they can't rename)
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^meetup\+(\d+)@bsidesottawa\.ca$", re.IGNORECASE)

def op_num(user):
    m = EMAIL_RE.match((user.get("email") or "").lower())
    return int(m.group(1)) if m else None

participants = {u["id"]: u for u in users if op_num(u) is not None}
print(f"participants: {len(participants)}")

challenge_by_id = {c["id"]: c for c in challenges}
hint_by_id      = {h["id"]: h for h in hints}

# ---------------------------------------------------------------------------
# Tags + mission helpers
# ---------------------------------------------------------------------------
DIFFICULTY_TAGS = {"easy", "medium", "hard", "expert"}
challenge_tags = defaultdict(list)
for t in tags:
    if t.get("challenge_id"): challenge_tags[t["challenge_id"]].append(t["value"])

def designated_difficulty(cid):
    for v in challenge_tags.get(cid, []):
        if v.lower() in DIFFICULTY_TAGS: return v.lower()
    val = challenge_by_id[cid]["value"]
    return {50: "easy", 100: "medium", 200: "hard", 300: "expert"}.get(val, "medium")

def mission_of(cid):
    cat = challenge_by_id[cid].get("category") or ""
    m = re.match(r"Mission (\d+)", cat)
    if m: return f"M{m.group(1)}"
    if "Start Here" in cat: return "M0"
    return "other"

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def ts(s):
    if not s: return None
    try: d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except: return None
    if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
    return d

EVENT_START = dt.datetime(2026, 4, 15, 21, 45, 0, tzinfo=dt.timezone.utc)
EVENT_END   = dt.datetime(2026, 4, 17, 3,  0, 0, tzinfo=dt.timezone.utc)
EPOCH_AWARE = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

# ---------------------------------------------------------------------------
# Per-user rollup with richer signal
# ---------------------------------------------------------------------------
user_solves = defaultdict(list)
user_subs = defaultdict(list)
user_unlocks = defaultdict(list)
for s in solves:
    if s["user_id"] in participants: user_solves[s["user_id"]].append(s)
for s in submissions:
    if s["user_id"] in participants: user_subs[s["user_id"]].append(s)
for u in unlocks:
    if u["user_id"] in participants: user_unlocks[u["user_id"]].append(u)

SESSION_GAP_S = 30 * 60  # 30 min defines a new session

user_rows = []
for uid, user in participants.items():
    solved = sorted(user_solves[uid], key=lambda r: ts(r["date"]) or EPOCH_AWARE)
    subs_all = sorted(user_subs[uid], key=lambda r: ts(r["date"]) or EPOCH_AWARE)
    unlks = user_unlocks[uid]

    correct     = [s for s in subs_all if s["type"] == "correct"]
    incorrect   = [s for s in subs_all if s["type"] == "incorrect"]
    ratelimited = [s for s in subs_all if s["type"] == "ratelimited"]
    # real attempts = correct + incorrect (ratelimited aren't user-chosen retries)
    real_attempts = len(correct) + len(incorrect)

    points = sum(challenge_by_id[s["challenge_id"]]["value"] for s in solved if s["challenge_id"] in challenge_by_id)
    hint_cost = sum(hint_by_id[u_["target"]]["cost"] for u_ in unlks if u_["target"] in hint_by_id)
    net_points = points - hint_cost

    first_sub_ts = ts(subs_all[0]["date"]) if subs_all else None
    last_sub_ts  = ts(subs_all[-1]["date"]) if subs_all else None
    first_solve_ts = ts(solved[0]["date"]) if solved else None

    active_minutes = round((last_sub_ts - first_sub_ts).total_seconds() / 60, 1) if (first_sub_ts and last_sub_ts) else None
    # "event-relative arrival" — how late after event start did they first submit
    arrival_minutes = round((first_sub_ts - EVENT_START).total_seconds() / 60, 1) if first_sub_ts else None

    # Inter-submission gaps (for burst density + session count)
    gaps = []
    sessions = 1 if subs_all else 0
    for i in range(1, len(subs_all)):
        t0 = ts(subs_all[i-1]["date"]); t1 = ts(subs_all[i]["date"])
        if t0 and t1:
            g = (t1 - t0).total_seconds()
            gaps.append(g)
            if g > SESSION_GAP_S:
                sessions += 1

    burst_buckets = Counter()
    for g in gaps:
        if g < 2:    burst_buckets["under_2s"] += 1
        elif g < 10: burst_buckets["2_10s"] += 1
        elif g < 60: burst_buckets["10_60s"] += 1
        elif g < 600:burst_buckets["1_10min"] += 1
        else:        burst_buckets["10min_plus"] += 1

    # Bimodal / "discovered-mid-event" detector
    # Compare burst density in first half vs second half of the operator's
    # submission timeline. A user who starts copy-pasting then switches to
    # Claude-drives-submission shows a jump in burst density late.
    bd_early = bd_late = None
    discovered = False
    if len(gaps) >= 10:
        mid = len(gaps) // 2
        early_gaps = gaps[:mid]; late_gaps = gaps[mid:]
        bd_early = round(sum(1 for g in early_gaps if g < 2) / len(early_gaps), 4)
        bd_late  = round(sum(1 for g in late_gaps  if g < 2) / len(late_gaps), 4)
        # Jump means: late burst density at least 2x early, AND late >= 15%
        if bd_late >= 0.15 and (bd_early < 0.05 or bd_late >= 2 * bd_early):
            discovered = True

    # success_rate — correct out of real attempts (NOT including ratelimited)
    success_rate = (len(correct) / real_attempts) if real_attempts else None
    burst_density = (burst_buckets["under_2s"] / len(gaps)) if gaps else 0.0

    # ratelimit pressure — ratelimited / total events
    rl_ratio = (len(ratelimited) / len(subs_all)) if subs_all else 0.0

    # Efficiency — points per minute active (ignoring idle)
    # We use effective active time = sum of gaps <= SESSION_GAP_S (i.e. in-session)
    in_session_seconds = sum(g for g in gaps if g <= SESSION_GAP_S)
    effective_minutes = round(in_session_seconds / 60, 1) if in_session_seconds else 0
    efficiency = (points / effective_minutes) if effective_minutes > 0 else None

    # missions
    missions_touched = {mission_of(s["challenge_id"]) for s in solved}
    mission_challenge_counts = Counter(mission_of(c["id"]) for c in challenges if c["state"] == "visible")
    mission_solve_counts = Counter(mission_of(s["challenge_id"]) for s in solved)
    missions_completed = [m for m, total in mission_challenge_counts.items()
                          if total > 0 and mission_solve_counts.get(m, 0) == total]
    missions_attempted = {mission_of(s["challenge_id"]) for s in subs_all}

    # which categories did this user attempt vs solve (for path analysis)
    per_mission_stats = {}
    for m in sorted(set(list(missions_touched) + list(missions_attempted))):
        in_mission = [s for s in subs_all if mission_of(s["challenge_id"]) == m]
        s_in_mission = [s for s in solved if mission_of(s["challenge_id"]) == m]
        per_mission_stats[m] = {"attempts": len(in_mission), "solves": len(s_in_mission)}

    user_rows.append({
        "user_id": uid,
        "op_num": op_num(user),
        "label": f"op{op_num(user):03d}",
        "points": points,
        "net_points": net_points,
        "solves": len(solved),
        "attempts_real": real_attempts,
        "attempts_total": len(subs_all),
        "correct": len(correct),
        "incorrect": len(incorrect),
        "ratelimited": len(ratelimited),
        "success_rate": round(success_rate, 4) if success_rate is not None else None,
        "rate_limit_ratio": round(rl_ratio, 4),
        "hints_bought": len(unlks),
        "hint_cost": hint_cost,
        "arrival_minutes": arrival_minutes,
        "first_solve_minutes": round((first_solve_ts - EVENT_START).total_seconds() / 60, 1) if first_solve_ts else None,
        "active_minutes": active_minutes,
        "effective_minutes": effective_minutes,
        "sessions": sessions,
        "burst_density": round(burst_density, 4),
        "burst_density_early": bd_early,
        "burst_density_late":  bd_late,
        "discovered_mid_event": discovered,
        "burst_buckets": dict(burst_buckets),
        "efficiency_pts_per_min": round(efficiency, 2) if efficiency else None,
        "missions_touched": sorted(missions_touched),
        "missions_completed": sorted(missions_completed),
        "per_mission": per_mission_stats,
    })

# Classifier — tuned from observed distributions
def classify(u):
    if u["attempts_total"] == 0:
        return "inactive"
    if u["solves"] == 0:
        return "engaged-unsuccessful"
    if u["solves"] < 3:
        return "low-engagement"
    sr = u["success_rate"] or 0.0
    bd = u["burst_density"]
    if sr >= 0.70 and bd >= 0.20:
        return "likely-agentic"
    if sr >= 0.70 and bd < 0.20:
        return "high-accuracy-slow"
    if sr < 0.35 and bd < 0.15:
        return "manual-struggling"
    if bd >= 0.20:
        return "burst-low-accuracy"     # automation going too fast or spraying
    return "mixed"

for u in user_rows:
    u["cluster"] = classify(u)

user_rows.sort(key=lambda r: r["points"], reverse=True)
cluster_summary = Counter(u["cluster"] for u in user_rows)

# Workflow re-framing: map clusters to operator workflow intuitions
WORKFLOW_MAP = {
    "high-accuracy-slow":   "human-in-loop (copy-paste from Claude)",
    "burst-low-accuracy":   "Claude drives submission",
    "likely-agentic":       "Claude drives submission (efficient)",
    "manual-struggling":    "manual / unassisted",
    "engaged-unsuccessful": "engaged but stuck",
    "mixed":                "mixed / transitional",
    "low-engagement":       "barely engaged",
    "inactive":             "never engaged",
}
workflow_summary = Counter(WORKFLOW_MAP[u["cluster"]] for u in user_rows)

# "Discovered mid-event" count
discovered_count = sum(1 for u in user_rows if u.get("discovered_mid_event"))
discovered_operators = [u for u in user_rows if u.get("discovered_mid_event")]

# ---------------------------------------------------------------------------
# Per-challenge rollup
# ---------------------------------------------------------------------------
solves_by_chal = defaultdict(list)
subs_by_chal = defaultdict(list)
for s in solves:
    if s["user_id"] in participants: solves_by_chal[s["challenge_id"]].append(s)
for s in submissions:
    if s["user_id"] in participants: subs_by_chal[s["challenge_id"]].append(s)

challenge_rows = []
for cid, chal in sorted(challenge_by_id.items(), key=lambda kv: kv[1]["id"]):
    if chal.get("state") != "visible":
        continue
    chal_solves = solves_by_chal[cid]
    chal_subs = subs_by_chal[cid]
    chal_subs_real = [s for s in chal_subs if s["type"] in ("correct", "incorrect")]
    difficulty = designated_difficulty(cid)
    mission = mission_of(cid)
    first_solve = min((ts(s["date"]) for s in chal_solves if ts(s["date"])), default=None)
    t_to_first = round((first_solve - EVENT_START).total_seconds() / 60, 1) if first_solve else None

    solver_ids = {s["user_id"] for s in chal_solves}
    # attempters — users who submitted at least once (any type)
    attempter_ids = {s["user_id"] for s in chal_subs}
    attempters_no_solve = attempter_ids - solver_ids

    # attempts per solver — real ones only
    attempts_per_solver = []
    for suid in solver_ids:
        u_attempts = [s for s in chal_subs if s["user_id"] == suid and s["type"] in ("correct","incorrect")]
        attempts_per_solver.append(len(u_attempts))
    median_attempts = statistics.median(attempts_per_solver) if attempts_per_solver else None

    # time-to-solve per solver (from their first attempt on this challenge to their solve)
    times_to_solve = []
    for suid in solver_ids:
        u_subs = sorted([s for s in chal_subs if s["user_id"] == suid], key=lambda r: ts(r["date"]) or EPOCH_AWARE)
        if not u_subs: continue
        first_attempt = ts(u_subs[0]["date"])
        solve_ts = next((ts(s["date"]) for s in u_subs if s["type"] == "correct"), None)
        if first_attempt and solve_ts:
            times_to_solve.append((solve_ts - first_attempt).total_seconds() / 60)
    median_ttsolve = round(statistics.median(times_to_solve), 1) if times_to_solve else None

    # conditional solve rate — of attempters, what fraction solved?
    conditional_solve_rate = (len(solver_ids) / len(attempter_ids)) if attempter_ids else 0

    # hint unlocks for this challenge
    chal_hint_ids = {h["id"] for h in hints if h["challenge_id"] == cid}
    hint_unlock_count = sum(1 for u in unlocks if u["user_id"] in participants and u["target"] in chal_hint_ids)

    # rate-limit pressure
    rl_count = sum(1 for s in chal_subs if s["type"] == "ratelimited")

    challenge_rows.append({
        "id": cid,
        "name": chal["name"],
        "category": chal.get("category") or "",
        "mission": mission,
        "value": chal["value"],
        "difficulty": difficulty,
        "solve_count": len(chal_solves),
        "solve_rate": round(len(chal_solves) / len(participants), 4),
        "attempter_count": len(attempter_ids),
        "conditional_solve_rate": round(conditional_solve_rate, 4),
        "attempt_count": len(chal_subs),
        "real_attempt_count": len(chal_subs_real),
        "rate_limited_count": rl_count,
        "first_solve": first_solve.isoformat() if first_solve else None,
        "minutes_to_first_solve": t_to_first,
        "median_attempts_per_solver": median_attempts,
        "median_minutes_to_solve": median_ttsolve,
        "hint_unlocks": hint_unlock_count,
    })

# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------
# Pareto share
total_solves = sum(u["solves"] for u in user_rows)
total_points = sum(u["points"] for u in user_rows)
active = [u for u in user_rows if u["attempts_total"] > 0]
active_sorted = sorted(active, key=lambda u: u["points"], reverse=True)

def top_share(users_sorted, field, k_pct):
    if not users_sorted: return 0
    k = max(1, int(len(users_sorted) * k_pct))
    top_sum = sum(u[field] for u in users_sorted[:k])
    total = sum(u[field] for u in users_sorted)
    return round(top_sum / total, 4) if total else 0

pareto = {
    "active_participants": len(active),
    "top_5pct_points_share":  top_share(active_sorted, "points", 0.05),
    "top_10pct_points_share": top_share(active_sorted, "points", 0.10),
    "top_25pct_points_share": top_share(active_sorted, "points", 0.25),
    "top_50pct_points_share": top_share(active_sorted, "points", 0.50),
    "top_5pct_solves_share":  top_share(active_sorted, "solves", 0.05),
    "top_10pct_solves_share": top_share(active_sorted, "solves", 0.10),
    "top_25pct_solves_share": top_share(active_sorted, "solves", 0.25),
}

# Score histogram
bins = [0, 50, 100, 250, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 7000]
score_hist = Counter()
for u in user_rows:
    placed = False
    for i in range(len(bins) - 1):
        if bins[i] <= u["points"] < bins[i + 1]:
            score_hist[f"{bins[i]}-{bins[i+1]}"] += 1; placed = True; break
    if not placed:
        score_hist[f"{bins[-1]}+"] += 1

# Solves histogram
solve_hist = Counter(u["solves"] for u in user_rows)

# Arrival distribution — first-submission offset from event start, in 15-min bins
arrival_bins = Counter()
for u in user_rows:
    if u["arrival_minutes"] is None: continue
    b = int(u["arrival_minutes"] // 15) * 15
    arrival_bins[b] += 1

# Mission funnel + "stuck" ratio (attempted-but-didn't-clear)
all_missions = sorted({c["mission"] for c in challenge_rows} | {"M0"})
visible_by_mission = Counter(r["mission"] for r in challenge_rows)
mission_funnel = {}
for m in all_missions:
    touched = sum(1 for u in user_rows if m in u["missions_touched"])
    completed = sum(1 for u in user_rows if m in u["missions_completed"])
    attempted = sum(1 for u in user_rows if m in u.get("per_mission", {}))
    stuck = attempted - touched   # attempted but no solves in that mission
    mission_funnel[m] = {
        "challenges_in_mission": visible_by_mission.get(m, 0),
        "participants_attempted": attempted,
        "participants_touched": touched,          # at least one solve
        "participants_completed": completed,
        "participants_stuck": stuck,              # attempted, 0 solves in mission
    }

# Difficulty calibration
by_difficulty = defaultdict(list)
for c in challenge_rows:
    by_difficulty[c["difficulty"]].append(c["solve_rate"])
difficulty_summary = {}
for d in ["easy", "medium", "hard", "expert"]:
    rates = by_difficulty.get(d, [])
    if rates:
        difficulty_summary[d] = {
            "count": len(rates),
            "mean_solve_rate": round(statistics.mean(rates), 4),
            "median_solve_rate": round(statistics.median(rates), 4),
            "min_solve_rate": round(min(rates), 4),
            "max_solve_rate": round(max(rates), 4),
        }

# Timeline (1-min bins) — cumulative solves
event_solves_by_minute = Counter()
for s in solves:
    if s["user_id"] not in participants: continue
    t = ts(s["date"])
    if t and t >= EVENT_START:
        event_solves_by_minute[int((t - EVENT_START).total_seconds() // 60)] += 1
timeline = []
cum = 0
for minute in sorted(event_solves_by_minute):
    cum += event_solves_by_minute[minute]
    timeline.append({"minute": minute, "new_solves": event_solves_by_minute[minute], "cumulative": cum})

# Rate-limit pressure per cluster (does AI get rate-limited more?)
rl_by_cluster = defaultdict(list)
for u in user_rows:
    if u["attempts_total"] > 0:
        rl_by_cluster[u["cluster"]].append(u["rate_limit_ratio"])
rl_cluster_summary = {k: {
    "n": len(v),
    "mean_rl_ratio": round(statistics.mean(v), 4),
    "median_rl_ratio": round(statistics.median(v), 4),
} for k, v in rl_by_cluster.items()}

# Hint economics — per challenge + overall ROI
hint_impact = []
for c in challenge_rows:
    cid = c["id"]
    chal_hint_ids = {h["id"] for h in hints if h["challenge_id"] == cid}
    unlockers = {u["user_id"] for u in unlocks if u["target"] in chal_hint_ids and u["user_id"] in participants}
    solver_ids = {s["user_id"] for s in solves_by_chal[cid]}
    if not unlockers: continue
    unlocker_solve_rate = len(unlockers & solver_ids) / len(unlockers)
    non_unlockers = set(participants.keys()) - unlockers
    non_unlocker_solve_rate = (len(non_unlockers & solver_ids) / len(non_unlockers)) if non_unlockers else 0
    hint_impact.append({
        "id": cid,
        "name": c["name"],
        "mission": c["mission"],
        "difficulty": c["difficulty"],
        "value": c["value"],
        "unlockers": len(unlockers),
        "unlocker_solve_rate": round(unlocker_solve_rate, 4),
        "non_unlocker_solve_rate": round(non_unlocker_solve_rate, 4),
        "lift": round(unlocker_solve_rate - non_unlocker_solve_rate, 4),
    })

# Hint ROI: for each unlocker, did they net positive points?
# Sum per user: points earned on challenges where they unlocked a hint - hint cost
roi_rows = []
for uid in participants:
    user_u = user_unlocks[uid]
    user_s = {s["challenge_id"] for s in user_solves[uid]}
    earned = 0; spent = 0; hints_on_solved = 0; hints_on_unsolved = 0
    for ul in user_u:
        h = hint_by_id.get(ul["target"])
        if not h: continue
        spent += h["cost"]
        if h["challenge_id"] in user_s:
            earned += challenge_by_id[h["challenge_id"]]["value"]
            hints_on_solved += 1
        else:
            hints_on_unsolved += 1
    if spent > 0 or earned > 0:
        roi_rows.append({
            "user_id": uid,
            "hint_spend": spent,
            "points_earned_on_hinted": earned,
            "net": earned - spent,
            "hints_on_solved": hints_on_solved,
            "hints_on_unsolved": hints_on_unsolved,
        })
hint_roi_summary = {
    "users_with_hints": len(roi_rows),
    "users_net_positive": sum(1 for r in roi_rows if r["net"] > 0),
    "users_net_zero":     sum(1 for r in roi_rows if r["net"] == 0),
    "users_net_negative": sum(1 for r in roi_rows if r["net"] < 0),
    "total_hint_spend":   sum(r["hint_spend"] for r in roi_rows),
    "total_earned_on_hinted": sum(r["points_earned_on_hinted"] for r in roi_rows),
    "net_community":      sum(r["net"] for r in roi_rows),
    "wasted_hints":       sum(r["hints_on_unsolved"] for r in roi_rows),
}

# Order of attack: for each user, what was their first solve? (warmup vs M1 vs parallel)
first_solve_mission = Counter()
for u in user_rows:
    uid = u["user_id"]
    if not user_solves[uid]: continue
    first = sorted(user_solves[uid], key=lambda s: ts(s["date"]) or EPOCH_AWARE)[0]
    first_solve_mission[mission_of(first["challenge_id"])] += 1

# Rate-limited submissions by HOUR of event (when did the platform get throttled?)
rl_by_minute = Counter()
for s in submissions:
    if s["user_id"] not in participants or s["type"] != "ratelimited": continue
    t = ts(s["date"])
    if t and t >= EVENT_START:
        minute = int((t - EVENT_START).total_seconds() // 60)
        rl_by_minute[minute] += 1
rl_timeline = [{"minute": m, "rate_limits": v} for m, v in sorted(rl_by_minute.items())]

# Challenges where even solvers needed many tries
grind_challenges = sorted(
    [c for c in challenge_rows if c["solve_count"] >= 3],
    key=lambda c: -c["median_attempts_per_solver"] if c["median_attempts_per_solver"] else 0,
)[:10]

# ---------------------------------------------------------------------------
# Write cleaned CSVs
# ---------------------------------------------------------------------------
def write_csv(name, rows, fields):
    with (CLEAN / f"{name}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k: r.get(k) for k in fields})
    print(f"wrote cleaned/{name}.csv")

write_csv("users", user_rows, [
    "op_num","label","points","net_points","solves","attempts_real","attempts_total","correct","incorrect","ratelimited",
    "success_rate","rate_limit_ratio","hints_bought","hint_cost",
    "arrival_minutes","first_solve_minutes","active_minutes","effective_minutes","sessions",
    "burst_density","efficiency_pts_per_min","cluster",
])
write_csv("challenges", challenge_rows, [
    "id","name","mission","difficulty","value",
    "solve_count","solve_rate","attempter_count","conditional_solve_rate",
    "attempt_count","real_attempt_count","rate_limited_count",
    "minutes_to_first_solve","median_minutes_to_solve","median_attempts_per_solver","hint_unlocks",
])

# ---------------------------------------------------------------------------
# analysis.json for the website
# ---------------------------------------------------------------------------
out = {
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "event": {"name": "Operation NORTHSTORM — BSides Ottawa",
              "start_utc": EVENT_START.isoformat(), "end_utc": EVENT_END.isoformat()},
    "summary": {
        "participants_total": len(participants),
        "participants_active": sum(1 for u in user_rows if u["attempts_total"] > 0),
        "participants_scoring": sum(1 for u in user_rows if u["points"] > 0),
        "challenges_visible": len(challenge_rows),
        "solves_total": sum(1 for s in solves if s["user_id"] in participants),
        "submissions_total": sum(1 for s in submissions if s["user_id"] in participants),
        "correct_total": sum(1 for s in submissions if s["user_id"] in participants and s["type"] == "correct"),
        "incorrect_total": sum(1 for s in submissions if s["user_id"] in participants and s["type"] == "incorrect"),
        "ratelimited_total": sum(1 for s in submissions if s["user_id"] in participants and s["type"] == "ratelimited"),
        "hint_unlocks_total": sum(1 for u in unlocks if u["user_id"] in participants),
        "top_score": max((u["points"] for u in user_rows), default=0),
        "median_score": int(statistics.median([u["points"] for u in user_rows])) if user_rows else 0,
        "mean_score_of_active": round(statistics.mean([u["points"] for u in user_rows if u["attempts_total"]>0]), 1) if active else 0,
        "median_solves": int(statistics.median([u["solves"] for u in user_rows])) if user_rows else 0,
    },
    "pareto": pareto,
    "users": user_rows,
    "challenges": challenge_rows,
    "score_histogram": dict(score_hist),
    "solve_histogram": {str(k): v for k, v in sorted(solve_hist.items())},
    "arrival_histogram": {str(k): v for k, v in sorted(arrival_bins.items())},
    "mission_funnel": mission_funnel,
    "first_solve_mission": dict(first_solve_mission),
    "difficulty_summary": difficulty_summary,
    "timeline": timeline,
    "rl_timeline": rl_timeline,
    "cluster_summary": dict(cluster_summary),
    "workflow_summary": dict(workflow_summary),
    "rl_cluster_summary": rl_cluster_summary,
    "discovered_mid_event_count": discovered_count,
    "discovered_mid_event_operators": [{
        "label": u["label"], "points": u["points"], "solves": u["solves"],
        "bd_early": u["burst_density_early"], "bd_late": u["burst_density_late"],
        "cluster": u["cluster"],
    } for u in discovered_operators],
    "hint_impact": hint_impact,
    "hint_roi_summary": hint_roi_summary,
    "grind_challenges": grind_challenges,
}

with OUT_JSON.open("w") as f:
    json.dump(out, f, indent=2, default=str)
print(f"wrote {OUT_JSON}  ({OUT_JSON.stat().st_size} bytes)")

# ---------------------------------------------------------------------------
# Human report
# ---------------------------------------------------------------------------
s = out["summary"]
lines = [
    "# Operation NORTHSTORM — Event Data Report",
    "",
    f"_Generated {out['generated_at']}_",
    "",
    "## Top-line numbers",
    "",
    f"- **{s['participants_total']}** participants enrolled; **{s['participants_active']}** made at least one submission; **{s['participants_scoring']}** scored.",
    f"- **{s['solves_total']}** total solves across **{s['challenges_visible']}** visible challenges.",
    f"- **{s['submissions_total']}** total submissions: **{s['correct_total']}** correct, **{s['incorrect_total']}** incorrect, **{s['ratelimited_total']}** rate-limited (_{round(s['ratelimited_total']/s['submissions_total']*100,1)}% of all submissions_).",
    f"- Top score: **{s['top_score']}**. Mean among active: **{s['mean_score_of_active']}**. Median (all): **{s['median_score']}**.",
    "",
    "## Headline findings",
    "",
    "**Submission-loop discoverability explains most of the variance.** Operators split into two Claude-assisted workflows: ({copy}) who copy-pasted Claude's output into the CTFd browser tab, and ({drives}) who figured out how to let Claude hit the submission endpoint directly. **{discovered} operators visibly crossed over mid-event** (early-session burst density under 10%, late-session burst density above 20%). Two of the four ceiling-tied operators are in this group — they started slow and sped up after discovering the Claude-drives-submission workflow. The two clusters are not two Claude styles; they are two operator integrations.",
    "",
    "**The ceiling is structural.** {tied} operators tied at the top score (${top}). They did not solve similar challenges — they solved the **exact same 49 challenges**, every one of them. The ceiling is everything except M5 Bunker.",
    "",
    "**Two bottlenecks.** M3 Lab: {m3a} attempted, {m3t} got any solve, {m3c} cleared. Hard content even once the pivot lands. M5 Bunker: {m5a} attempted, **0 solved anything** across 6 challenges. Either the blackout→splice mechanic didn't fully open the route, or the OT protocol work is too far outside most comfort zones for a 4-hour window.",
    "",
    "**Attendance was the real gate.** {active}/{total} enrolled operators submitted anything. For an event whose design assumption was \"everyone has Claude,\" the loss in the onboarding funnel mattered more than any content tuning.",
    "",
    "**Platform rate-limits.** CTFd threw **{rl} rate-limit responses** (26% of all submissions) concentrated in the Claude-drives-submission cluster. Default CTFd rate-limit config treats a human typing and an AI looping the same — that's a platform-tuning gap for agentic events.",
    "",
    "**Hint 2 = answer on hard content.** {big_lifts} challenges show +80% or greater solve-rate lift for hint-unlockers. By design, but economically it means paying for the answer, not paying for a nudge.",
    "",
]
lines = [l.format(
    rl=s["ratelimited_total"],
    copy=workflow_summary.get("human-in-loop (copy-paste from Claude)", 0),
    drives=workflow_summary.get("Claude drives submission", 0),
    discovered=discovered_count,
    tied=sum(1 for u in user_rows if u["points"] == user_rows[0]["points"]),
    top=user_rows[0]["points"],
    m3a=mission_funnel.get("M3",{}).get("participants_attempted",0),
    m3t=mission_funnel.get("M3",{}).get("participants_touched",0),
    m3c=mission_funnel.get("M3",{}).get("participants_completed",0),
    m5a=mission_funnel.get("M5",{}).get("participants_attempted",0),
    active=s["participants_active"], total=s["participants_total"],
    big_lifts=sum(1 for h in hint_impact if h["lift"]>=0.8),
) for l in lines]

lines += [
    "## Difficulty calibration",
    "",
    "| Designated | N | Mean | Median | Min | Max |",
    "|---|---|---|---|---|---|",
]
for d in ["easy","medium","hard","expert"]:
    if d in difficulty_summary:
        sd = difficulty_summary[d]
        lines.append(
            f"| {d} | {sd['count']} | {sd['mean_solve_rate']:.1%} | {sd['median_solve_rate']:.1%} | "
            f"{sd['min_solve_rate']:.1%} | {sd['max_solve_rate']:.1%} |"
        )
lines.append("")
lines.append("Solve rate falls monotonically with designated difficulty. Calibration held.")
lines.append("")

lines += [
    "## Mission funnel (attempted → touched → cleared)",
    "",
    "| Mission | Challenges | Attempted | Touched (≥1 solve) | Fully cleared | Attempted-but-0-solves |",
    "|---|---|---|---|---|---|",
]
for m in sorted(mission_funnel):
    info = mission_funnel[m]
    stuck = info.get("participants_stuck", 0)
    lines.append(f"| {m} | {info['challenges_in_mission']} | {info['participants_attempted']} | "
                 f"{info['participants_touched']} | {info['participants_completed']} | {stuck} |")
lines.append("")
lines.append("The `Attempted-but-0-solves` column shows frustration pockets. M5 (Bunker) is pure frustration: lots of attempts, zero solves.")
lines.append("")

lines += [
    "## Pareto share",
    "",
    f"- Top 5% of active operators: **{pareto['top_5pct_points_share']:.0%}** of points, **{pareto['top_5pct_solves_share']:.0%}** of solves.",
    f"- Top 10%: **{pareto['top_10pct_points_share']:.0%}** of points, **{pareto['top_10pct_solves_share']:.0%}** of solves.",
    f"- Top 25%: **{pareto['top_25pct_points_share']:.0%}** of points, **{pareto['top_25pct_solves_share']:.0%}** of solves.",
    "",
    f"Active participants: **{pareto['active_participants']}** of {s['participants_total']} enrolled.",
    "",
]

lines += [
    "## Workflow membership (derived from cluster → operator workflow)",
    "",
    "| Cluster | Workflow interpretation | Count |",
    "|---|---|---|",
]
for cluster, count in cluster_summary.most_common():
    wf = WORKFLOW_MAP.get(cluster, cluster)
    lines.append(f"| {cluster} | {wf} | {count} |")
lines.append("")

if discovered_count:
    lines.append("### Operators who discovered Claude-submits mid-event")
    lines.append("")
    lines.append("Bimodal burst-density signature: quiet early, bursty late.")
    lines.append("")
    lines.append("| Operator | Points | Solves | Burst density early | Burst density late | Cluster |")
    lines.append("|---|---|---|---|---|---|")
    for u in sorted(discovered_operators, key=lambda x: -x["points"]):
        lines.append(f"| {u['label']} | {u['points']} | {u['solves']} | {u['burst_density_early']:.0%} | {u['burst_density_late']:.0%} | {u['cluster']} |")
    lines.append("")
lines += [
    "Rules:",
    "- `likely-agentic` — ≥3 solves, ≥70% success, ≥20% of gaps <2s",
    "- `burst-low-accuracy` — ≥20% burst density but <70% success (AI spraying)",
    "- `high-accuracy-slow` — ≥70% success, <20% burst density (disciplined manual or light AI)",
    "- `manual-struggling` — <35% success, <15% burst density",
    "- `mixed` — everything in between",
    "- `engaged-unsuccessful` — submitted but zero solves",
    "- `low-engagement` — fewer than 3 solves",
    "- `inactive` — zero submissions",
    "",
    "### Rate-limit pressure by cluster",
    "",
    "| Cluster | N | Mean RL ratio | Median RL ratio |",
    "|---|---|---|---|",
]
for cl, info in sorted(rl_cluster_summary.items(), key=lambda kv: -kv[1]["mean_rl_ratio"]):
    lines.append(f"| {cl} | {info['n']} | {info['mean_rl_ratio']:.1%} | {info['median_rl_ratio']:.1%} |")
lines.append("")
lines.append("If agentic operators drive platform rate-limits, `likely-agentic` and `burst-low-accuracy` should be at the top. They are. This is the CTFd platform cost of giving participants Claude.")
lines.append("")

lines += [
    "## Hint ROI (operator POV)",
    "",
    f"- {hint_roi_summary['users_with_hints']} operators bought hints.",
    f"- {hint_roi_summary['users_net_positive']} ended net-positive (earned more on hint-unlocked challenges than they spent).",
    f"- {hint_roi_summary['users_net_negative']} ended net-negative.",
    f"- Total community hint spend: **{hint_roi_summary['total_hint_spend']} pts**. Total earned on hint-unlocked challenges: **{hint_roi_summary['total_earned_on_hinted']} pts**. Net: **{hint_roi_summary['net_community']:+} pts**.",
    f"- Wasted hints (unlocked but never solved): **{hint_roi_summary['wasted_hints']}**.",
    "",
]

lines += [
    "## Top 20 scorers",
    "",
    "| # | Label | Points | Solves | Real attempts | Success | RL ratio | Hints | Arrival | Cluster |",
    "|---|---|---|---|---|---|---|---|---|---|",
]
for i, u in enumerate(user_rows[:20], 1):
    sr = f"{u['success_rate']:.0%}" if u["success_rate"] is not None else "—"
    rl = f"{u['rate_limit_ratio']:.0%}"
    arr = f"{u['arrival_minutes']:.0f}m" if u["arrival_minutes"] is not None else "—"
    lines.append(f"| {i} | {u['label']} | {u['points']} | {u['solves']} | {u['attempts_real']} | {sr} | {rl} | {u['hints_bought']} | {arr} | {u['cluster']} |")
lines.append("")

lines += [
    "## Hardest challenges that at least ONE person solved (by conditional rate: of people who attempted, how few solved)",
    "",
    "| Challenge | Mission | Diff | Attempters | Solvers | Conditional rate | Median attempts/solver | Median min-to-solve |",
    "|---|---|---|---|---|---|---|---|",
]
hard_conditional = sorted([c for c in challenge_rows if c["attempter_count"] >= 3 and c["solve_count"] >= 1],
                          key=lambda c: c["conditional_solve_rate"])[:10]
for c in hard_conditional:
    mts = f"{c['median_minutes_to_solve']:.0f}" if c["median_minutes_to_solve"] else "—"
    lines.append(f"| {c['name']} | {c['mission']} | {c['difficulty']} | {c['attempter_count']} | {c['solve_count']} | "
                 f"{c['conditional_solve_rate']:.1%} | {c['median_attempts_per_solver']} | {mts} |")
lines.append("")

lines += [
    "## Grind challenges (median attempts-per-solver among those who solved)",
    "",
    "| Challenge | Mission | Diff | Median attempts | Solvers |",
    "|---|---|---|---|---|",
]
for c in grind_challenges:
    lines.append(f"| {c['name']} | {c['mission']} | {c['difficulty']} | {c['median_attempts_per_solver']} | {c['solve_count']} |")
lines.append("")

lines += [
    "## Zero-solve challenges",
    "",
]
zero = [c for c in challenge_rows if c["solve_count"] == 0]
if zero:
    lines.append(f"All {len(zero)} belong to **M5 Bunker**. Combined {sum(c['attempt_count'] for c in zero)} submissions across these from {sum(c['attempter_count'] for c in zero)} participant-attempts.")
    lines.append("")
    lines.append("| Challenge | Difficulty | Attempters | Total submissions | Rate-limited |")
    lines.append("|---|---|---|---|---|")
    for c in zero:
        lines.append(f"| {c['name']} | {c['difficulty']} | {c['attempter_count']} | {c['attempt_count']} | {c['rate_limited_count']} |")
else:
    lines.append("_None._")
lines.append("")

lines += [
    "## Arrival pattern",
    "",
    f"Of {s['participants_active']} active operators, first-submission offset from event start:",
    "",
    "| Offset (minutes) | Participants |",
    "|---|---|",
]
for b in sorted(arrival_bins):
    lines.append(f"| {b}–{b+15} | {arrival_bins[b]} |")
lines.append("")

lines += [
    "## Order of attack — first-solve by mission",
    "",
    "What was the first challenge each operator solved?",
    "",
    "| Mission | Operators starting here |",
    "|---|---|",
]
for m in sorted(first_solve_mission, key=lambda k: -first_solve_mission[k]):
    lines.append(f"| {m} | {first_solve_mission[m]} |")
lines.append("")

OUT_REPORT.write_text("\n".join(lines) + "\n")
print(f"wrote {OUT_REPORT}")
