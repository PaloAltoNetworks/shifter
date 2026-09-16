# Range Functional Smoke

Automated proof that a participant can actually *use* a range: an interactive
terminal that exchanges real data with a range host, and a Guacamole session
driven to a client-level connection. Run it on demand—before an event, or
after a change that touches terminal or Guacamole wiring.

Implementation: `uat/range-functional-smoke/` (issue
[#987](https://github.com/Brad-Edwards/shifter/issues/987)).

## What it closes

The existing automated live-range check
([post-deploy range smoke](../architecture/post-deploy-smoke-test-preflight-218.md))
stops at a TCP connection to ports 22 and 3389. Whether a participant can open a
working terminal or a Guacamole session was verified only by hand. The June 2026
failures that reached users—terminal SSH wiring and Guacamole bootstrap—are
exactly the class a port probe cannot see.

Unlike the rest of this directory's protocols, this one needs **no Browser
steps**: it drives the real HTTP, WebSocket, and Guacamole paths end to end.

## Preconditions

- A deployed tenant that is already healthy (this check does not re-prove
  deployment health or image boot—those are the
  [built-image stack smoke](../architecture/built-image-stack-smoke-preflight-922.md)
  and deploy-health verify).
- A **known-up example range**: owned by the account you authenticate as, in
  `ready`, with an instance whose authored `participant_access` declares the
  channel you are checking. A missing or not-ready range fails the run—it is
  never a green skip.
- A participant session, from either actor source below.

## Actor sources

Both are real logins. There is no bypass: `/dev-login/` is dev-only and disabled
outside `ENVIRONMENT=development`, and no Admin-SDK custom token, superuser path,
or smoke-only session endpoint is used.

**Captured session**—log in normally in a browser, copy the `sessionid` cookie
into a `0600` file, and pass `--session-file`. The harness refuses a
group- or world-readable file.

**Front-door login**—for a credential the tenant operator provisioned: password
sign-in, the TOTP second factor, then the product's own
`POST /auth/identity/session/` exchange, which independently re-checks
`emailVerified` and enrolled MFA before creating the session. Secrets are read
from `SMOKE_PASSWORD` / `SMOKE_TOTP_SECRET` / `SMOKE_API_KEY`, never argv.

!!! note "Identity Platform tenants require enrolled MFA"
    `config.identity_platform` refuses to create an app session for an account
    with no enrolled factor. A validation account therefore needs a TOTP factor
    enrolled before it can be used—for a headless run *or* by a human.

## Running it

```bash
cd uat/range-functional-smoke
uv sync --group dev
uv run range-functional-smoke \
  --origin https://<portal-host> \
  --environment <name> \
  --target-role attacker \
  --protocol rdp \
  --session-file ~/.shifter/smoke.session
```

`--protocol` defaults to `rdp`: the terminal check already proves the SSH path,
so driving Guacamole over RDP widens real coverage. Exit code is `0` only on an
overall pass. A production-looking target is refused unless
`--allow-production` is passed.

## Reading the verdict

The report lists every check separately—range readiness, target selection,
terminal socket, terminal exchange, and the four Guacamole evidence levels—and
is a pass only if all of them passed.

Two rows carry the product claim:

- `terminal_nonce_exchange`—input produced matching output from the guest's own
  shell. A WebSocket upgrade alone is *not* sufficient.
- `guacamole_session_connected`—guacd completed the protocol handshake and
  opened the session. Bootstrap `succeeded` and one-time URL delivery are
  necessary but *not* sufficient: they prove only that the server minted a
  credential.

A run that reports `guacamole_bootstrap_succeeded: passed` alongside
`guacamole_session_connected: failed` means the portal is minting session
credentials that guacd cannot use—a real user-facing outage, not a harness
problem.

The report carries identifiers and provenance only: no cookie, token, Guacamole
URL, SSH key, private address, raw response body, traceback, or terminal output.

## Scope

This check proves the participant journey. It is not an isolation proof (see
[range-escape validation](../ops/range-escape-validation.md)), not a capacity
proof (see `uat/event-load-harness`), and not scenario-content verification.
It never provisions or destroys a range: the example range belongs to whoever
created it.
