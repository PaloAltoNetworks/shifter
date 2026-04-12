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
