from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


BASH_BIN = shutil.which("bash") or "/bin/bash"
ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def test_entrypoint_creates_guacamole_home(tmp_path) -> None:
    guacamole_home = tmp_path / ".guacamole"
    env = os.environ.copy()
    env["GUACAMOLE_HOME"] = str(guacamole_home)

    result = subprocess.run(  # noqa: S603
        [
            BASH_BIN,
            str(ENTRYPOINT),
            "sh",
            "-c",
            'test -d "$GUACAMOLE_HOME"',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert guacamole_home.is_dir()


def test_entrypoint_skips_default_guacamole_home_creation(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mkdir_log = tmp_path / "mkdir.log"
    fake_mkdir = bin_dir / "mkdir"
    fake_mkdir.write_text(
        "#!/bin/sh\n"
        f"echo called >> {mkdir_log}\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_mkdir.chmod(0o755)

    env = os.environ.copy()
    env.pop("GUACAMOLE_HOME", None)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(  # noqa: S603
        [
            BASH_BIN,
            str(ENTRYPOINT),
            "sh",
            "-c",
            "true",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert not mkdir_log.exists()
