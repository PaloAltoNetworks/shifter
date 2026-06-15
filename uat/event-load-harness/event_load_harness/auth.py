"""Actor sources: how the harness obtains identities to drive load as.

Three sources, matching the preflight's actor-source seam:

* ``manifest`` - a gitignored, 0600 TOML file of participant credentials/sessions.
* ``dev-login`` - generated dev-login actors for a *deployed dev* target only,
  driven through the documented ``/dev-login/`` access path.
* ``ctfd-csv`` - CTFd participant CSV (deferred with the CTFd surface).

Credentials are secret-bearing. ``Actor`` keeps password/session material off its
repr/str so it never lands in a log line, and the manifest loader refuses a file
any other user can read.
"""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, field


class AuthError(Exception):
    """Raised for actor-source problems (bad manifest, unsafe permissions)."""


@dataclass
class Actor:
    """One identity the harness drives load as.

    ``label`` is the only safe-to-log identifier. ``email`` is withheld from
    repr (treated as semi-sensitive PII), and ``password`` / ``session_cookie``
    are secret and never rendered.
    """

    label: str
    email: str = field(repr=False)
    user_type: str = "standard"
    password: str | None = field(default=None, repr=False)
    session_cookie: str | None = field(default=None, repr=False)

    def __str__(self) -> str:
        return f"Actor({self.label}, type={self.user_type})"


def _label(index: int) -> str:
    return f"actor-{index:04d}"


def load_actor_manifest(path: str) -> list[Actor]:
    """Load actors from a 0600 TOML manifest, refusing world/group-readable files."""
    try:
        st = os.stat(path)
    except OSError as exc:
        raise AuthError(f"actor manifest not readable: {path}") from exc

    if stat.S_IMODE(st.st_mode) & 0o077:
        raise AuthError(
            f"actor manifest {path} is group/world accessible; it holds credentials. "
            "Restrict it with `chmod 600` (0600) before use."
        )

    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AuthError(f"could not parse actor manifest {path}: {exc}") from exc

    raw_actors = data.get("actor", [])
    if not raw_actors:
        raise AuthError(f"actor manifest {path} contains no [[actor]] entries")

    actors: list[Actor] = []
    for i, entry in enumerate(raw_actors, start=1):
        email = entry.get("email")
        if not email:
            raise AuthError(f"actor manifest {path}: entry {i} is missing 'email'")
        password = entry.get("password")
        session_cookie = entry.get("session_cookie")
        if not password and not session_cookie:
            raise AuthError(f"actor manifest {path}: entry {i} ({_label(i)}) needs a 'password' or 'session_cookie'")
        actors.append(
            Actor(
                label=_label(i),
                email=email,
                user_type=entry.get("user_type", "standard"),
                password=password,
                session_cookie=session_cookie,
            )
        )
    return actors


def dev_login_actors(
    count: int, email_pattern: str = "loadtest+{i}@example.com", user_type: str = "standard"
) -> list[Actor]:
    """Generate ``count`` dev-login actors for a deployed-dev target.

    These drive the documented ``/dev-login/`` path (email + user_type, no
    password). They are valid only where dev-login is enabled; the harness never
    broadens ``DEV_LOGIN_ALLOWED_*`` or makes this work against production.
    """
    if count <= 0:
        raise AuthError("dev_login_actors count must be > 0")
    return [Actor(label=_label(i), email=email_pattern.format(i=i), user_type=user_type) for i in range(1, count + 1)]


def ctfd_csv_actors(path: str) -> list[Actor]:
    """Load actors from a CTFd participant CSV. Deferred with the CTFd surface."""
    raise NotImplementedError(
        "ctfd-csv actor source is deferred until the CTFd load surface lands; "
        "use 'manifest' or 'dev-login' for the core portal profile"
    )
