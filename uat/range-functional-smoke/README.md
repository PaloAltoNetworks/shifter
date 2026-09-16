# Range functional smoke (#987)

Proves the two participant flows that no automated check covered before: an
**interactive terminal that exchanges real data with a range host**, and a
**Guacamole session that reaches a client-level connection**. Both run through
the product boundary against a positively selected, known-up example range on a
deployed tenant.

On demand only. It is not in `deploy.yml`, gates no deploy, and takes no cloud
role—the participant session is the only authority it acts with.

## Why it exists

| Existing check | Live range | Terminal + Guacamole |
| --- | --- | --- |
| Built-image stack smoke (`scripts/stack-smoke/`, #922) | no | no, explicitly out of scope |
| Post-deploy range smoke (`cms.post_deploy_smoke`, #218) | yes | no—TCP reachability only |
| **This** | yes | yes |

The June 2026 failures that reached users—terminal SSH wiring, Guacamole
bootstrap—sit precisely in that gap. A TCP probe to ports 22 and 3389 cannot
see them.

## What counts as a pass

Every required check must pass; a missing, blocked, skipped, timed-out, or
errored check is never a pass.

| Check | Sufficient evidence |
| --- | --- |
| `range_owned_ready` | the owner-scoped projection reports an active, ready range |
| `target_selected` | the authored logical role resolves to an instance the portal offers a terminal for |
| `terminal_socket_open` | the routed consumer accepted the socket |
| `terminal_nonce_exchange` | **input produced matching output from the guest's own shell** |
| `guacamole_bootstrap_accepted` | HTTP 202—queue admission only |
| `guacamole_bootstrap_succeeded` | a signed URL was minted |
| `guacamole_url_delivered` | the one-time URL was consumed by this client |
| `guacamole_session_connected` | **guacd completed the handshake and opened the session** |

The two bold rows are the ones that mean the product works. Bootstrap success
proves only that the server minted a credential—accepting it as "Guacamole
works" would preserve the exact gap this check exists to close.

### The echo hazard

An interactive shell echoes what it receives, so a naive `echo <nonce>` probe
would match its own typed input and pass against a shell that never ran
anything. The command is therefore split—`echo "SMOKE""<nonce>"`—so the
echoed input contains `SMOKE""<nonce>` while only real output contains the
joined `SMOKE<nonce>`. See `tests/test_terminal.py::TestEchoHazard`.

## Running it

```bash
cd uat/range-functional-smoke
uv sync --group dev

# Actor source 1: a session captured from a normal browser login (0600 file).
uv run range-functional-smoke \
  --origin https://gcp.shifter.keplerops.com \
  --environment gcp-dev \
  --session-file ~/.shifter/smoke.session

# Actor source 2: the full front-door login for an operator-provisioned
# credential. Secrets come from the environment, never argv.
SMOKE_PASSWORD=... SMOKE_TOTP_SECRET=... SMOKE_API_KEY=... \
uv run range-functional-smoke \
  --origin https://gcp.shifter.keplerops.com \
  --environment gcp-dev \
  --email range-validator@example.com \
  --credential-env
```

Exit code is `0` only on an overall pass. A production-looking target is refused
unless `--allow-production` is passed, so a run cannot be aimed at production or
a live event tenant by accident.

**HTTPS is required.** The harness carries a replayable ID token, a live
`sessionid` cookie (on HTTP *and* in the websocket handshake), and a signed
Guacamole token in a tunnel query string—all stealable by a passive observer
over `http`/`ws`. Plaintext is refused for the configured origin and for every
server-returned URL alike; `--allow-plaintext-loopback` relaxes it for a
loopback host only, never for a real one.

Pace repeated runs: Identity Platform rate-limits TOTP sign-in and answers
`QUOTA_EXCEEDED` when a credential is exercised in tight succession.

## Design boundaries

- **The profile carries no connection material.** Only a logical selector (role,
  protocol) crosses the boundary. Host, port, username, key, and password stay
  inside the portal, because resolving them is part of what is under test.
- **The example range is never destroyed.** It belongs to whoever created it.
- **No auth bypass.** `/dev-login/` is a dev-only path (and disabled outside
  `ENVIRONMENT=development`); no Admin-SDK custom token, no superuser, no
  smoke-only session endpoint. Both actor sources are real logins.
- **Evidence is bounded and non-secret.** No cookie, token, Guacamole URL,
  private address, raw body, traceback, or terminal output reaches the report.

## Tests

`uv run pytest -q` covers the deterministic layers—profile safety, target
selection, nonce matching, Guacamole state classification, TOTP derivation,
redaction, and fail-closed verdict composition. The live executor targets a
deployed tenant and is exercised by operator runs, never by mocking the app
(ADR-019).
