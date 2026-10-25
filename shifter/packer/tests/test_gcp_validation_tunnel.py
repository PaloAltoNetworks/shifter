"""Exercise the runner's guest-boot retry boundary without cloud resources."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("guest_result,expected,attempts", [(0, 0, 2), (1, 1, 2)])
def test_tunnel_survives_guest_boot_and_preserves_validation_result(tmp_path, guest_result, expected, attempts):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        # Simulate gcloud's early connection check failing while the VM boots.
        # Disabling that check allows the listener to serve subsequent probes.
        "gcloud": """#!/bin/bash
case " $* " in
  *" --iap-tunnel-disable-connection-check "*) touch "$TEST_STATE/ready" ;;
  *) exit 1 ;;
esac
exec /bin/sleep 30
""",
        "timeout": """#!/bin/bash
/bin/sleep 0.02
test -f "$TEST_STATE/ready"
""",
        "sleep": "#!/bin/bash\nexec /bin/sleep 0.02\n",
        "ssh": """#!/bin/bash
echo attempt >> "$TEST_STATE/attempts"
if [[ ! -f "$TEST_STATE/booted" ]]; then
  touch "$TEST_STATE/booted"
  exit 255
fi
exit "$TEST_GUEST_RESULT"
""",
    }
    for name, content in scripts.items():
        path = bin_dir / name
        path.write_text(content)
        path.chmod(0o755)
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        TEST_STATE=str(tmp_path),
        TEST_GUEST_RESULT=str(guest_result),
        VM="synthetic-candidate",
        ZONE="us-central1-a",
        GCP_PROJECT_ID="example-project",
        IMAGE_TYPE="ubuntu",
        SSH_KEY=str(tmp_path / "synthetic-key"),
    )
    script = Path(__file__).parents[1] / "gcp/scripts/validate/gather-evidence.sh"
    # Only the checked-in script and test-owned executable fixtures are run.
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(script)], env=env, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == expected, result.stderr
    assert (tmp_path / "attempts").read_text().splitlines() == ["attempt"] * attempts
