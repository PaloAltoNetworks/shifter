# Operation NORTHSTORM — Event Data & Analysis

Dumps, analysis, and a local viewer for the BSides Ottawa Polaris CTF event (15–16 April 2026).

## Layout

```
analysis/
├── data/
│   ├── raw/            CTFd DB dump (git-ignored — contains PII + flag answers)
│   ├── cleaned/        Scrubbed CSVs safe to share (no PII, no flag strings)
│   ├── analysis.json   Aggregated stats powering the website
├── scripts/
│   └── analyze.py      Computes cleaned/* and analysis.json from raw/*
├── website/            Local static viewer (Chart.js)
├── REPORT.md           Human-readable summary
├── serve.sh            Spin up the viewer on http://127.0.0.1:8090
└── README.md
```

## View the site locally

```
./serve.sh
# open http://127.0.0.1:8090/website/
```

## Regenerate from live CTFd

Raw dumps are not committed. To refresh:

1. Ensure you have a working admin token at `~/.cache/polaris_ctfd_token` and SSM access to the CTFd EC2 host (`i-08410b6d5d90beaf1` in the `panw-shifter-dev-workstation` profile).
2. Dump all tables via the ad-hoc pattern:

   ```
   # on the CTFd host:
   docker exec ctfd-ctfd-1 python3 <<'PY'
   import os, sys, json, datetime
   os.chdir('/opt/CTFd'); sys.path.insert(0,'/opt/CTFd')
   from CTFd import create_app
   from CTFd.models import (Users, Challenges, Hints, Flags, Solves,
                            Submissions, Unlocks, Awards, Tags, Tracking)
   from sqlalchemy import inspect as sqla_inspect
   app = create_app()
   def d(r):
     o={}
     for c in sqla_inspect(r.__class__).columns.keys():
       v = getattr(r,c)
       if isinstance(v, datetime.datetime): v = v.isoformat()
       o[c]=v
     return o
   with app.app_context():
     for n, m in [('users',Users),('challenges',Challenges),('hints',Hints),
                  ('flags',Flags),('tags',Tags),('solves',Solves),
                  ('submissions',Submissions),('unlocks',Unlocks),
                  ('awards',Awards),('tracking',Tracking)]:
       json.dump([d(r) for r in m.query.all()], open(f'/tmp/{n}.json','w'), default=str)
   PY
   ```

3. Copy the JSON files back to `data/raw/` on your workstation. The dump size is ~2 MB uncompressed; for SSM the easy path is `tar czf /tmp/dumps.tar.gz /tmp/*.json` and split into 14 KB base64 chunks (see `/tmp/pull_chunks.py` pattern used to seed this repo).

4. Re-run the analysis:

   ```
   python3 scripts/analyze.py
   ```

   Overwrites `data/cleaned/*.csv`, `data/analysis.json`, and `REPORT.md`.

## What's in the cleaned output

### `data/cleaned/users.csv`

Per-participant roll-up. `label = op{N}` where N is the `meetup+N` number. No emails or IPs.

Columns: `op_num, label, points, net_points, solves, attempts, correct, incorrect,
success_rate, hints_bought, hint_cost, active_minutes, burst_density, cluster`.

### `data/cleaned/challenges.csv`

Per-challenge empirical stats.

Columns: `id, name, mission, difficulty, value, solve_count, solve_rate,
attempt_count, minutes_to_first_solve, median_attempts_per_solver, hint_unlocks`.

### `data/analysis.json`

Everything the website consumes: summary numbers, score/solve histograms, mission funnel,
difficulty calibration, per-user rollup, per-challenge rollup, timeline (cumulative solves
across the event window), cluster membership counts, and hint-economics table.

## Cluster heuristic

Participants are grouped on two axes:

- **success rate** = correct submissions / total submissions
- **burst density** = fraction of inter-submission gaps under 2 seconds

Labels:

| Cluster              | Rule                                    | Intent                                  |
|----------------------|------------------------------------------|-----------------------------------------|
| `likely-agentic`     | solves ≥ 3, success ≥ 80%, bursts ≥ 30% | Efficient AI-assisted                   |
| `high-accuracy-slow` | success ≥ 80%, bursts < 30%             | Careful manual or light AI             |
| `manual-struggling`  | success < 50%, bursts < 20%             | Mostly-human brute force               |
| `low-engagement`     | fewer than 3 solves                      | Logged in but barely played             |
| `inactive`           | 0 submissions                            | Enrolled but never engaged              |
| `mixed`              | everything else                          | Burst-heavy spray-and-pray, late AI access, etc. |

These are descriptive, not a classifier. Mixed is not a judgment — it's where operators
with delayed AI access, manual brute-forcers, and heavy experimenters all land.

## Privacy

- `data/raw/` is git-ignored. It contains real flag strings and IP addresses.
- Cleaned outputs (`cleaned/`, `analysis.json`, `REPORT.md`) use `op{NNN}` labels, omit IPs
  entirely, and never carry the flag answer key.
- The website never loads `data/raw/`, only `data/analysis.json`.
