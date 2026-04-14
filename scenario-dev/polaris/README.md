# POLARIS / NORTHSTORM CTF — Scenario Development

Consolidated working directory for the NORTHSTORM CTF range (Operation POLARIS).
Everything related to designing, building, deploying, and testing the range
lives under this folder.

## Layout

```
scenario-dev/polaris/
├── design/                         authoritative spec — source of truth
│   ├── architecture.md             zone layout, flags, missions, progression
│   ├── range-diagram.md            network topology diagram
│   ├── benchmark-report.md         mechag benchmark data
│   ├── shared-constants.md         cross-asset values (serials, override codes)
│   └── assets/                     per-asset design docs
│       ├── A0-boreas-website.md    Boreas OSINT site
│       ├── A1-mail-server.md       Postfix / Dovecot / Roundcube
│       ├── A2-domain-controller.md Windows AD (GCE VM, not docker)
│       ├── A3-web-app.md           Flask intranet + SQLi / LFI / admin panel
│       ├── A4-file-share.md        Samba share with PDFs + xlsx
│       ├── A5-scada-generator.md   SCADA HMI + Modbus interlock PLC
│       ├── A6-engineering-workstation.md  Linux SSH + 47 sim archives
│       ├── A7-source-repo.md       Gitea with aurora org + deleted schematic
│       ├── A8-research-database.md PostgreSQL compartments + GPG key blob
│       ├── A9-splice-landing.md    Alpine relay into the Bunker
│       ├── A10-tail-controller.md  Modbus PLC, challenge-response
│       ├── A11-leg-controller.md   Modbus PLC, timed gait sequence
│       ├── A12-arms-controller.md  Modbus PLC, rolling nonce + XOR
│       ├── A13-brain.md            TCP 9100 binary handshake + override
│       └── A14-kali.md             Participant attack box
│
├── build/                          container build artifacts
│   ├── docker-compose.yml          range topology: shared / corporate / scada / lab / bunker-ot
│   ├── ctfd-challenges.json        CTFd flag metadata
│   ├── dns/                        BIND sidecar (boreas-systems.ctf + boreas.local zones, AXFR enabled)
│   ├── a0/ ... a14/                Dockerfiles + runtime configs per asset
│   └── A0-boreas-website/ ...      content generators (server.py, build_*.py, bootstrap.sh, init SQL)
│       A14-kali/
│
├── tests/                          everything test-related
│   ├── setup.sh                    build + up + wait ready
│   ├── reset.sh                    force-recreate sticky-state services (a5/a10/a11/a12/a13)
│   ├── run-all-smoketests.sh       full sweep: reset + 15 asset smoketests + isolation
│   ├── isolation-smoketest.sh      cross-cutting network boundary validation (70 checks)
│   ├── smoketests/                 one per asset, pointed at the live range from its pivot container
│   │   ├── A0-smoketest.sh ... A14-smoketest.(sh|py)
│   └── walkthroughs/               step-by-step happy-path participant guides, grouped by flag range
│       ├── README.md
│       ├── 00-range-access.md
│       ├── 00-range-access-docker.md
│       ├── flags-01-06-osint.md
│       ├── flags-07-19-front-office.md
│       ├── flags-20-30-lab.md
│       └── flags-31-36-bunker.md
│
└── notes/                          spike notes + handoff / TODO
    ├── HANDOFF.md                  session handoff context
    ├── BUILD-TODO.md               outstanding build items
    ├── a2-samba-ad-spike.md        why we gave up on Samba AD DC and switched to Windows
    ├── a6-a7-golden-build.md       a6 + a7 golden build notes
    └── a7-gitea-spike.md           Gitea bootstrap spike
```

## Source of truth

**`design/` is canonical.** If implementation (`build/`, `tests/`) disagrees
with the design doc, fix the implementation. Never edit design to match
whatever got built without explicit user approval. Smoketests and walkthroughs
exist to validate that the implementation matches the design.

## Getting started

1. **Deploy** — on the range host (ctf-range-builder GCP VM):
   ```
   rsync -a scenario-dev/polaris/ ctf-range-builder:/home/atomik/range/
   ssh ctf-range-builder 'bash /home/atomik/range/tests/setup.sh'
   ```

2. **Test** — run the full sweep:
   ```
   ssh ctf-range-builder 'bash /home/atomik/range/tests/run-all-smoketests.sh'
   ```
   Expected: `16 / 16 asset sweeps PASS`, `NORTHSTORM full range: PASS`.

3. **Reset** — before each test or between participant sessions:
   ```
   ssh ctf-range-builder 'bash /home/atomik/range/tests/reset.sh'
   ```
   Puts sticky-state services (a5/a10/a11/a12/a13) back to fresh pre-unlock
   state.

## Asset pivot map (who tests what, and from where)

| Asset  | Network attachment       | Smoketest runs from | Why |
|--------|--------------------------|---------------------|-----|
| A0     | shared                   | a14-kali            | a14 is on shared |
| A1     | corporate                | a14-kali            | a14 is on corporate |
| A2     | external GCP VM          | a14-kali            | routed via host |
| A3     | corporate + scada + lab  | a14-kali            | a14 reaches on corporate |
| A4     | corporate                | a14-kali            | a14 is on corporate |
| A5     | scada (VLAN 40)          | a3-intranet         | only A3 reaches scada |
| A6     | lab (VLAN 30)            | a3-intranet         | only A3 reaches lab |
| A7     | shared + lab             | a14-kali            | a14 is on shared |
| A8     | lab (VLAN 30)            | a3-intranet         | only A3 reaches lab |
| A9     | bunker-ot (VLAN 50)      | a9-splice (self)    | A9 is the bunker entry point |
| A10-13 | bunker-ot (VLAN 50)      | a9-splice           | only the bunker can reach bunker |
| A14    | shared + corporate       | a14-kali (self)     | platform readiness check |
| (net)  | cross-cutting            | range host          | docker exec into each source container |
