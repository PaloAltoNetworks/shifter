# Terminal WebSocket Capacity: Implementation Decision (#847)

Status: implemented

Date: 2026-05-31

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/847>

Companion: [terminal-websocket-capacity-preflight-847.md](terminal-websocket-capacity-preflight-847.md)

## Decision

Bound terminal websocket load inside the existing portal ASGI process rather
than extracting a separate terminal runtime. The change adds per-process and
per-user session caps, idle and maximum-duration timeouts, and a low-frequency
output poll, all environment-tunable. No new deployable component is introduced.

The concurrency envelope below is derived analytically from per-session resource
accounting, not from a load test. There is no environment available to measure
in before the next live event, so the controls are set conservatively and made
tunable so they can be adjusted during the event without a redeploy.

## Why not extract a separate runtime now

The issue and the preflight both recommend measuring before changing the runtime
topology. Two constraints override "measure first" for this change:

- No measurement environment exists before the event. An analytical envelope
  plus tunable, conservative limits is the available path to a safer event.
- A separate ASGI service, target group, or gateway adds a running component to
  operate, monitor, and pay for, two weeks before a live event. That raises cost
  and operational risk, the opposite of the goal.

The in-process defects that hurt an event are fixable without that blast radius.
Runtime extraction stays a documented follow-up, to be driven by evidence
gathered during or after the event (see Follow-ups).

## Defects addressed

| Defect | Before | After |
| --- | --- | --- |
| Idle busy-loop | `_read_ssh_output` polled `receive(timeout=0.1)`, waking every idle session ~10x/second; on shell EOF the empty-read loop spun at full speed until `is_connected` flipped. | Poll interval is `TERMINAL_READ_POLL_SECONDS` (default 30s). EOF is detected via `SSHConnection.at_eof()` and breaks promptly. Output latency is unchanged: bytes are delivered as soon as they arrive. |
| No concurrency bound | Unlimited sessions per process; a flood or reconnect storm could exhaust file descriptors and the event loop. | `_TerminalSessionRegistry` enforces `TERMINAL_MAX_SESSIONS` (process) and `TERMINAL_MAX_SESSIONS_PER_USER`. Over-cap connects are rejected before any SSH work with close code `4503` (`SERVICE_UNAVAILABLE`). |
| Leaked sessions | A session lived until the client disconnected; abandoned tabs and dropped clients held resources indefinitely. | Idle sessions close after `TERMINAL_IDLE_TIMEOUT_SECONDS`; all sessions close after `TERMINAL_MAX_SESSION_SECONDS`. |

The `4503` rejection is retryable on the client (`terminal.js` retries all codes
except `4001` and `4003`, with exponential backoff). Transient pressure
self-heals as other sessions end, without a permanent failure for the user.

## Controls

Defined in `config/settings.py`, read by `mission_control.consumers`. A value
`<= 0` disables that individual limit.

| Setting | Default | Meaning |
| --- | --- | --- |
| `TERMINAL_MAX_SESSIONS` | 200 | Active terminal sessions per ASGI process. |
| `TERMINAL_MAX_SESSIONS_PER_USER` | 10 | Active terminal sessions per user, per process. |
| `TERMINAL_IDLE_TIMEOUT_SECONDS` | 1800 | Close a session after this much inactivity (no input or output). |
| `TERMINAL_MAX_SESSION_SECONDS` | 28800 | Hard ceiling on a single session's lifetime. |
| `TERMINAL_READ_POLL_SECONDS` | 30 | How often an idle read loop wakes to enforce timeouts and notice EOF. Does not bound output latency. |

## Analytical concurrency envelope

Deployment facts (verified):

- The portal runs a single Daphne process per pod or instance, so one event
  loop serves all websockets and HTTP on that node (`entrypoint.sh`).
- GCP runs 2 `portal-web` replicas by default
  (`platform/k8s/gcp/base/web-deployment.yaml`, pod memory limit 1Gi). AWS runs
  the portal container on EC2, single instance or ASG.

Per-session cost:

| Resource | Per active session |
| --- | --- |
| File descriptors | ~2 (client websocket + SSH TCP socket) |
| `asyncio` tasks | 1 read task |
| Memory | asyncssh connection + channel buffers, order of 10s to low 100s of KB |
| DB writes | 2 audit rows over the session lifecycle (connect, disconnect); no per-keystroke writes |
| Idle event-loop wakeups | `1 / TERMINAL_READ_POLL_SECONDS` (≈0.033/s at the 30s default) |

Idle scheduler load is the dominant win. At 200 idle sessions the old 0.1s poll
generated ~2000 wakeups/second of pure idle overhead on the single event loop;
the 30s poll generates ~6.7/second, roughly a 300x reduction. That headroom is
what keeps non-terminal HTTP, range-status websockets, and Guacamole URL
bootstrap responsive while terminals are open.

The binding ceiling is file descriptors. At the default cap of 200 sessions a
process needs ~400 FDs for terminals alone, plus HTTP sockets, DB connections,
and the Redis channel layer. A container `nofile` limit of 1024 (a common
default) leaves thin headroom. The default cap of 200 is chosen to stay well
under that; raising the cap requires confirming the container FD limit first
(see Follow-ups).

With defaults, cluster capacity is ~200 concurrent terminals per AWS instance
and ~400 across the two GCP replicas. Size the caps for the event from expected
concurrent participants times terminals per participant, leaving FD headroom.

## Ownership boundaries

The capacity controls preserve the seams the preflight requires. No
authorization logic moves into the transport layer.

| Concern | Owner |
| --- | --- |
| WebSocket transport lifecycle and capacity enforcement | `mission_control.consumers.SSHConsumer`, `_TerminalSessionRegistry` |
| User ownership, active-range, readiness, instance, and secret-reference checks | `engine.services.connect_terminal` / `get_ssh_connection_info` |
| SSH client mechanics, including `at_eof()` | `engine.ssh.SSHConnection` |
| Capacity and timeout policy values | `config/settings.py` environment knobs |

The session registry is process-local by design. It protects each ASGI process
individually and needs no shared state. A future cross-process or cross-pod
global cap would require a shared store and is out of scope here.

## Follow-ups

These need evidence from a real event or environment and are deliberately not in
this change:

1. AWS ALB idle timeout. The portal ALB sets no `idle_timeout`
   (`platform/terraform/modules/portal/alb/main.tf`), so the AWS default of 60s
   applies. An idle terminal is dropped by the load balancer well before the
   in-process idle timeout. The in-process limits cannot fix a load-balancer
   drop. Options: raise the ALB `idle_timeout`, or add a client or server
   keepalive ping. Pick one with a measured reconnect story.
2. Confirm the container `nofile` limit on each runtime before raising
   `TERMINAL_MAX_SESSIONS` above the default.
3. Runtime extraction. If a single ASGI process proves insufficient after the
   event, extract terminal websockets into an independently scalable runtime
   (dedicated ASGI deployment or target group), reusing the same engine
   authorization seam and the `/ws/terminal/<instance_uuid>/` contract.
