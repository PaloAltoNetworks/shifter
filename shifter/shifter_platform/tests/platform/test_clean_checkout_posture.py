"""Clean-checkout test posture invariants (#1529 / REV1 Q6/Q7).

REV1 Q7: a clean-checkout test run must establish the same environment CI does,
rather than inheriting the production HTTPS posture because CI happens to export
``DJANGO_DEBUG=true``. REV1 Q6: a test run must never dispatch the local
provisioner, which shells out to a real subprocess and leaks it. Both are
established in the settings themselves via ``config._runtime_env.IS_TEST_RUN`` so
they hold for a bare ``uv run pytest``, not only under CI's injected environment
or the ``Makefile`` targets.

The check resolves Django settings in a subprocess with the posture variables
scrubbed and ``dotenv`` neutralized, so it fails even in CI -- or on a developer
machine with a ``.env`` -- if the settings-level defaults regress. An in-process
assertion would be masked by the ambient environment CI/`.env` already provides.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]

# Posture variables CI or a developer ``.env`` might inject. Scrubbing them from
# the child environment is what makes this a genuine clean-checkout test.
_POSTURE_VARS = (
    "DJANGO_DEBUG",
    "TESTING",
    "TEST_DB_BACKEND",
    "ENVIRONMENT",
    "DJANGO_SECRET_KEY",
    "LOCAL_PROVISIONER",
)

_CHILD_SCRIPT = textwrap.dedent(
    """
    # Neutralize any ambient .env before settings import: find_dotenv() walks up
    # from config/settings.py, so it would otherwise reintroduce a developer
    # posture and mask the settings-level default under test.
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False

    import django

    django.setup()
    from django.conf import settings

    assert settings.DEBUG is True, "clean-checkout test run must default DJANGO_DEBUG on (Q7)"
    engine = settings.DATABASES["default"]["ENGINE"]
    assert "sqlite" in engine, f"clean-checkout test run must default to the SQLite fast lane, got {engine}"
    assert settings.LOCAL_PROVISIONER == "", (
        f"a test run must force the local provisioner off, got {settings.LOCAL_PROVISIONER!r} (Q6)"
    )
    print("CLEAN_CHECKOUT_POSTURE_OK")
    """
)


def test_clean_checkout_establishes_ci_posture() -> None:
    # Start from a scrubbed environment, then set only what a bare test run
    # provides: TESTING marks the run (``config._runtime_env.IS_TEST_RUN``) and a
    # synthetic key satisfies the settings guard. DJANGO_DEBUG / TEST_DB_BACKEND are
    # deliberately absent so the settings-level defaults decide, and
    # LOCAL_PROVISIONER is set to a dispatching value to prove it is forced off.
    child_env = {k: v for k, v in os.environ.items() if k not in _POSTURE_VARS}
    child_env["TESTING"] = "1"
    child_env["DJANGO_SECRET_KEY"] = "clean-checkout-posture-test"
    child_env["LOCAL_PROVISIONER"] = "subprocess"
    child_env["DJANGO_SETTINGS_MODULE"] = "config.settings"
    # The package root (so ``config`` and siblings import) + its parent (so the
    # package itself imports) must be on the path, matching the package pytest
    # ``pythonpath = [".."]``.
    child_env["PYTHONPATH"] = os.pathsep.join([str(PACKAGE_ROOT), str(PACKAGE_ROOT.parent)])

    result = subprocess.run(  # noqa: S603 - trusted argv: this interpreter + a static in-repo script constant
        [sys.executable, "-c", _CHILD_SCRIPT],
        cwd=str(PACKAGE_ROOT),
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"clean-checkout posture failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "CLEAN_CHECKOUT_POSTURE_OK" in result.stdout
