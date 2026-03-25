# ACTIVE Requirements Matrix

Status values:

- `Implemented`
- `Partial`
- `Not Implemented`

Ground Control trace note:

- `TESTS linked` means the requirement currently has at least one `TESTS` trace link in Ground Control.
- `No TESTS link` means it does not.

| UID | Title | Status | Ground Control Tests | Notes |
| --- | --- | --- | --- | --- |
| `CTF-002` | Scoring System | `Partial` | `TESTS linked` | Core scoring exists, but hint penalties are not reliably applied and scoring-mode configurability is not obvious in the current model. |
| `CTF-005` | Team Management | `Partial` | `TESTS linked` | Team score, invite code, and membership exist, but app-level team creation/captain workflow looks thin. |
| `CTF-006` | Participant Management | `Partial` | `TESTS linked` | Invite/import/resend/disqualify flows exist, but invited and registered are effectively collapsed by auto-registration. |
| `CTF-008` | Notifications & Communications | `Partial` | `TESTS linked` | Immediate email flows exist, but scheduled reminder/announcement execution is incomplete. |
| `CTF-009` | Range Integration | `Partial` | `TESTS linked` | Provisioning and browser-access intent exist, but range identifier handling is inconsistent and likely broken on the participant page. |
| `CTF-010` | Scheduled Tasks & Automation | `Partial` | `No TESTS link` | Task rows and a scheduler command exist, but reminder execution is stubbed and auto-start remains unresolved. |
| `CTF-013` | Administration | `Partial` | `No TESTS link` | Organizer dashboards and analytics pages exist, but some underlying analytics are wrong or shallow. |
| `CTF-1001` | Scheduled Task Framework | `Partial` | `No TESTS link` | One-shot task execution, status tracking, and failure recording exist, but cron-like recurring tasks and organizer manual triggering are not evident. |
| `CTF-1002` | Automated Range Spinup | `Partial` | `No TESTS link` | Pre-spinup timing and throttling exist, but organizer delay notification is missing. |
| `CTF-1006` | Scheduler Auto-Start | `Partial` | `No TESTS link` | Infra traces exist, but the application still relies on a separate scheduler process model. |
| `CTF-101` | Challenge CRUD | `Implemented` | `TESTS linked` | CRUD, event scoping, flags, category, difficulty, and release time support are present. |
| `CTF-102` | Challenge Categories | `Partial` | `TESTS linked` | Grouping/filtering exist, but categories are fixed globally instead of organizer-defined per event. |
| `CTF-103` | Challenge Difficulty Levels | `Implemented` | `No TESTS link` | Difficulty field and participant display are present. |
| `CTF-104` | Static Flag Validation | `Implemented` | `No TESTS link` | Exact-match validation, attempt recording, and irreversible correct solves are present. |
| `CTF-108` | Challenge File Attachments | `Implemented` | `TESTS linked` | File upload, size limits, secure download URLs, and delete behavior are implemented. |
| `CTF-111` | Challenge Release Scheduling | `Partial` | `No TESTS link` | Release-time gating exists, but there is no explicit scheduled release processor or one-minute guarantee. |
| `CTF-116` | Flag Format Specification | `Partial` | `TESTS linked` | Flag format exists, but it is modeled per challenge instead of per event and is not shown on the event page. |
| `CTF-118` | Programmable Flag Validation | `Implemented` | `TESTS linked` | Programmable and HTTP validator hooks exist with per-flag configuration and validation paths. |
| `CTF-1305` | Submission History | `Partial` | `No TESTS link` | Submission records and some organizer/participant views exist, but event-wide filtering/search/configurability are incomplete. |
| `CTF-201` | Standard Scoring | `Implemented` | `TESTS linked` | Fixed-point scoring is present and score totals are computed from awarded points plus awards. |
| `CTF-203` | Hint Penalty Application | `Not Implemented` | `TESTS linked` | Hint use is logged but not persisted, and 100 percent penalties floor at `1` instead of `0`. |
| `CTF-205` | First Blood Tracking | `Implemented` | `TESTS linked` | First blood is computed and surfaced on challenge/admin views. |
| `CTF-206` | Score Calculation | `Partial` | `TESTS linked` | Score totals are deterministic, but hint-usage accounting is broken. |
| `CTF-401` | Individual Scoreboard | `Partial` | `No TESTS link` | Ranking service exists, but the participant scoreboard view/API/template contract is broken and row click-through is missing. |
| `CTF-406` | Tie-Breaking Rules | `Implemented` | `No TESTS link` | Earlier `last_solve_time` wins, and the participant help text documents the rule. |
| `CTF-407` | Challenge Statistics | `Partial` | `No TESTS link` | Statistics exist, but solve-rate denominator is wrong and participant visibility is not clearly event-configurable. |
| `CTF-701` | Event Lifecycle | `Implemented` | `TESTS linked` | State enum, transition map, and service validation align with the active-state-machine requirement. |
| `CTF-901` | Per-Participant Range Provisioning | `Partial` | `TESTS linked` | Participant-specific provisioning and range status tracking exist, but the access path has identifier and data-shape inconsistencies. |
| `CTF-906` | Per-Event Instance Visibility | `Partial` | `No TESTS link` | CTF-only users are filtered in Mission Control, but participant event selection is not strongly scoped and range access uses ambiguous identifiers. |

## Highest-Priority Requirement Gaps

If the goal is to move the active requirement set toward real implementation completeness, I would prioritize these first:

1. `CTF-203` / `CTF-206` / `CTF-002`: make hint usage and scoring correct.
2. `CTF-009` / `CTF-901` / `CTF-906`: fix CTF range identifier contracts and event scoping.
3. `CTF-010` / `CTF-1001` / `CTF-1002` / `CTF-1006`: finish the scheduler path end-to-end.
4. `CTF-401` / `CTF-407` / `CTF-013`: make reporting surfaces match the service layer and requirement text.
