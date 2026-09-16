"""Live orchestration: drive both flows through the product boundary.

Everything here talks to a deployed tenant, so it is exercised by operator runs
rather than CI (ADR-019: the app is not mocked to satisfy an acceptance claim).
The deterministic layers it composes — profile validation, target selection,
nonce matching, Guacamole state classification, verdict composition — are unit
tested on their own.

Ordering is deliberate: session, then range/target, then terminal, then
Guacamole. Each stage records its own check codes and a failure stops the
dependent stages while still producing a complete, fail-closed report.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

import httpx
import websockets

from range_functional_smoke import guacamole, session, targets, terminal
from range_functional_smoke.profile import RunProfile
from range_functional_smoke.results import CheckCode, RunResults, Status


class Runner:
    """One bounded run against one example range."""

    def __init__(self, profile: RunProfile, *, credential=None, session_cookie: str | None = None) -> None:
        if credential is None and not session_cookie:
            raise ValueError("runner needs either an Identity Platform credential or an operator session cookie")
        self.profile = profile
        self._credential = credential
        self._session_cookie = session_cookie
        self.results = RunResults()

    async def run(self) -> RunResults:
        """Execute the run within the whole-run deadline."""
        try:
            await asyncio.wait_for(self._run(), timeout=self.profile.deadlines.run_seconds)
        except TimeoutError:
            self.results.record(
                CheckCode.RANGE_OWNED_READY,
                Status.TIMED_OUT,
                f"run exceeded its {self.profile.deadlines.run_seconds:.0f}s deadline",
            )
        return self.results

    async def _run(self) -> None:
        async with httpx.AsyncClient(
            base_url=self.profile.origin,
            timeout=30.0,
            # Never chase an off-origin redirect with the session attached.
            follow_redirects=False,
        ) as client:
            started = time.monotonic()
            try:
                await self._authenticate(client)
            except session.SessionError as exc:
                # A login failure must still produce a fail-closed report: every
                # downstream check stays absent, which the verdict counts as a
                # failure. Crashing here would lose the evidence entirely.
                self.results.record(CheckCode.SESSION_ESTABLISHED, Status.FAILED, str(exc), _ms(started))
                return
            self.results.record(
                CheckCode.SESSION_ESTABLISHED, Status.PASSED, "participant session established", _ms(started)
            )

            target = await self._select_target(client)
            if target is None:
                return
            await self._terminal_check(client, target)
            await self._guacamole_check(client, target)

    # --- session ---------------------------------------------------------- #

    async def _authenticate(self, client: httpx.AsyncClient) -> None:
        deadline = self.profile.deadlines.session_seconds
        if self._session_cookie:
            host = httpx.URL(self.profile.origin).host
            client.cookies.set("sessionid", self._session_cookie, domain=host, path="/")
            return
        id_token = await session.identity_platform_id_token(client, self._credential, timeout=deadline)
        await session.exchange_id_token_for_session(client, id_token, timeout=deadline)

    # --- range / target ---------------------------------------------------- #

    async def _select_target(self, client: httpx.AsyncClient) -> targets.RangeTarget | None:
        started = time.monotonic()
        try:
            response = await client.get(targets.RANGE_PATH, headers={"Accept": "application/json"})
        except Exception:
            self.results.record(CheckCode.RANGE_OWNED_READY, Status.ERROR, "range projection request failed")
            return None
        if response.status_code >= 400:
            self.results.record(
                CheckCode.RANGE_OWNED_READY, Status.FAILED, f"range projection returned HTTP {response.status_code}"
            )
            return None

        try:
            target = targets.select_target(response.json(), role=self.profile.target_role)
        except targets.TargetError as exc:
            self.results.record(CheckCode.RANGE_OWNED_READY, Status.BLOCKED, str(exc))
            return None
        except ValueError:
            self.results.record(CheckCode.RANGE_OWNED_READY, Status.ERROR, "range projection was not valid JSON")
            return None

        self.results.record(
            CheckCode.RANGE_OWNED_READY,
            Status.PASSED,
            f"owned range {target.range_id} ({target.scenario_id}) is ready",
            _ms(started),
        )
        self.results.record(
            CheckCode.TARGET_SELECTED,
            Status.PASSED,
            f"selected authored role {target.role!r} ({target.os_type}) with a terminal offered",
        )
        return target

    # --- terminal ---------------------------------------------------------- #

    async def _terminal_check(self, client: httpx.AsyncClient, target: targets.RangeTarget) -> None:
        url = terminal.terminal_ws_url(self.profile.origin, target.instance_uuid)
        headers = [
            ("Cookie", "; ".join(f"{name}={value}" for name, value in client.cookies.items())),
            ("Origin", self.profile.websocket_origin),
        ]
        nonce = terminal.make_nonce()
        started = time.monotonic()
        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                open_timeout=self.profile.deadlines.terminal_open_seconds,
                close_timeout=5,
            ) as socket:
                self.results.record(
                    CheckCode.TERMINAL_SOCKET_OPEN, Status.PASSED, "consumer accepted the socket", _ms(started)
                )
                await self._nonce_exchange(socket, nonce)
        except Exception as exc:
            code = getattr(getattr(exc, "rcvd", None), "code", None) or getattr(exc, "code", None)
            detail = f"terminal socket did not open (close code {code})" if code else "terminal socket did not open"
            self.results.record(CheckCode.TERMINAL_SOCKET_OPEN, Status.FAILED, detail, _ms(started))
            self.results.record(
                CheckCode.TERMINAL_NONCE_EXCHANGE, Status.BLOCKED, "no terminal socket to exchange data on"
            )

    async def _nonce_exchange(self, socket, nonce: str) -> None:
        started = time.monotonic()
        deadline = self.profile.deadlines.terminal_exchange_seconds
        try:
            await socket.send(terminal.input_frame(nonce))
            observed = await asyncio.wait_for(self._await_nonce(socket, nonce), timeout=deadline)
        except TimeoutError:
            observed = False
        except Exception:
            self.results.record(
                CheckCode.TERMINAL_NONCE_EXCHANGE, Status.FAILED, "terminal closed during the exchange", _ms(started)
            )
            return

        if observed:
            self.results.record(
                CheckCode.TERMINAL_NONCE_EXCHANGE,
                Status.PASSED,
                "input produced matching output from the range host",
                _ms(started),
            )
        else:
            self.results.record(
                CheckCode.TERMINAL_NONCE_EXCHANGE,
                Status.TIMED_OUT,
                f"no matching output within {deadline:.0f}s",
                _ms(started),
            )

    @staticmethod
    async def _await_nonce(socket, nonce: str) -> bool:
        """Accumulate output frames until the joined token appears."""
        buffer = ""
        while True:
            frame = await socket.recv()
            buffer = terminal.accumulate(buffer, terminal.output_text(frame))
            if terminal.nonce_observed(buffer, nonce):
                return True

    # --- guacamole --------------------------------------------------------- #

    async def _guacamole_check(self, client: httpx.AsyncClient, target: targets.RangeTarget) -> None:
        status_url = await self._bootstrap(client, target)
        if status_url is None:
            self._block_remaining_guacamole_checks(CheckCode.GUACAMOLE_BOOTSTRAP_SUCCEEDED)
            return
        url = await self._await_delivery(client, status_url)
        if url is None:
            self.results.record(
                CheckCode.GUACAMOLE_SESSION_CONNECTED, Status.BLOCKED, "no session URL was delivered to connect with"
            )
            return
        await self._connect_session(client, url)

    async def _bootstrap(self, client: httpx.AsyncClient, target: targets.RangeTarget) -> str | None:
        started = time.monotonic()
        path = guacamole.bootstrap_path(self.profile.protocol)
        try:
            response = await client.post(
                path,
                json={"instance_uuid": target.instance_uuid},
                headers=await self._csrf_headers(client),
            )
        except Exception:
            self.results.record(CheckCode.GUACAMOLE_BOOTSTRAP_ACCEPTED, Status.ERROR, "bootstrap request failed")
            return None

        if response.status_code != 202:
            self.results.record(
                CheckCode.GUACAMOLE_BOOTSTRAP_ACCEPTED,
                Status.FAILED,
                f"bootstrap returned HTTP {response.status_code}, expected 202",
                _ms(started),
            )
            return None

        payload = _safe_json(response)
        status_url = str(payload.get("status_url") or "")
        if not status_url:
            self.results.record(
                CheckCode.GUACAMOLE_BOOTSTRAP_ACCEPTED, Status.FAILED, "202 carried no status_url", _ms(started)
            )
            return None
        self.results.record(
            CheckCode.GUACAMOLE_BOOTSTRAP_ACCEPTED,
            Status.PASSED,
            f"queued ({payload.get('status', 'pending')})",
            _ms(started),
        )
        return status_url

    async def _await_delivery(self, client: httpx.AsyncClient, status_url: str) -> str | None:
        """Poll to SUCCEEDED, then take the one-time URL on that same poll.

        The successful poll *is* the delivery: it clears ``result_url`` and sets
        ``delivered_at`` server-side, so a second poll would get 410. The URL is
        returned in memory to the caller and never recorded.
        """
        started = time.monotonic()
        deadline = started + self.profile.deadlines.guacamole_bootstrap_seconds
        last = "no poll completed"
        while time.monotonic() < deadline:
            try:
                response = await client.get(status_url, headers={"Accept": "application/json"})
            except Exception:
                last = "status poll request failed"
                break
            poll = guacamole.classify_poll(response.status_code, _safe_json(response))
            if poll.delivered:
                self.results.record(
                    CheckCode.GUACAMOLE_BOOTSTRAP_SUCCEEDED,
                    Status.PASSED,
                    "signed session URL was minted",
                    _ms(started),
                )
                self.results.record(
                    CheckCode.GUACAMOLE_URL_DELIVERED, Status.PASSED, "one-time URL consumed by this client"
                )
                return str(_safe_json(response).get("url") or "")
            if poll.succeeded and not poll.delivered:
                last = "succeeded but the one-time URL was already consumed or expired"
                break
            if not poll.pending:
                last = f"bootstrap {poll.status or 'unknown'} (HTTP {poll.http_status}) {poll.error}".strip()
                break
            await asyncio.sleep(1.0)
        else:
            last = f"still pending after {self.profile.deadlines.guacamole_bootstrap_seconds:.0f}s"

        self.results.record(CheckCode.GUACAMOLE_BOOTSTRAP_SUCCEEDED, Status.FAILED, last, _ms(started))
        self.results.record(CheckCode.GUACAMOLE_URL_DELIVERED, Status.BLOCKED, "no successful bootstrap to deliver")
        return None

    async def _connect_session(self, client: httpx.AsyncClient, url: str) -> None:
        """Drive the delivered URL to a client-level guacd connection."""
        started = time.monotonic()
        try:
            target = guacamole.parse_session_url(
                url,
                base_origin=self.profile.origin,
                allow_plaintext_loopback=self.profile.allow_plaintext_loopback,
            )
        except guacamole.GuacamoleCheckError as exc:
            self.results.record(CheckCode.GUACAMOLE_SESSION_CONNECTED, Status.FAILED, str(exc), _ms(started))
            return

        deadline = self.profile.deadlines.guacamole_connect_seconds
        try:
            async with websockets.connect(
                guacamole.tunnel_ws_url(target),
                additional_headers=[("Origin", self.profile.websocket_origin)],
                subprotocols=["guacamole"],
                open_timeout=deadline,
                close_timeout=5,
            ) as tunnel:
                outcome = await asyncio.wait_for(self._await_ready(tunnel), timeout=deadline)
        except TimeoutError:
            outcome = "no ready instruction before the deadline"
        except Exception as exc:
            code = getattr(getattr(exc, "rcvd", None), "code", None) or getattr(exc, "code", None)
            outcome = f"tunnel refused ({code})" if code else "tunnel could not be opened"

        if outcome is True:
            self.results.record(
                CheckCode.GUACAMOLE_SESSION_CONNECTED,
                Status.PASSED,
                "guacd completed the handshake and opened the session",
                _ms(started),
            )
            return
        self.results.record(CheckCode.GUACAMOLE_SESSION_CONNECTED, Status.FAILED, str(outcome), _ms(started))

    @staticmethod
    async def _await_ready(tunnel) -> object:
        """Read the protocol stream until guacd says ``ready`` (or errors)."""
        stream = ""
        while len(stream) < 65536:
            frame = await tunnel.recv()
            stream += frame if isinstance(frame, str) else frame.decode("utf-8", "replace")
            if guacamole.has_ready_instruction(stream):
                return True
            if guacamole.is_error_instruction(stream):
                return "guacd returned an error instruction instead of opening the session"
        return "protocol stream ended without a ready instruction"

    def _block_remaining_guacamole_checks(self, *_codes: CheckCode) -> None:
        self.results.record(CheckCode.GUACAMOLE_BOOTSTRAP_SUCCEEDED, Status.BLOCKED, "bootstrap was never accepted")
        self.results.record(CheckCode.GUACAMOLE_URL_DELIVERED, Status.BLOCKED, "bootstrap was never accepted")
        self.results.record(CheckCode.GUACAMOLE_SESSION_CONNECTED, Status.BLOCKED, "bootstrap was never accepted")

    # --- helpers ----------------------------------------------------------- #

    async def _csrf_headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Session-authenticated POSTs keep CSRF; prime the token if absent."""
        if not client.cookies.get("csrftoken"):
            with contextlib.suppress(Exception):
                await client.get("/dashboard/", headers={"Accept": "text/html"})
        headers = {"Referer": f"{self.profile.origin}/"}
        token = client.cookies.get("csrftoken")
        if token:
            headers["X-CSRFToken"] = token
        return headers


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _safe_json(response) -> dict:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
