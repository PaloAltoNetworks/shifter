"""Keep OpenFGA conformance mandatory without selecting it in a bare PostgreSQL lane."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[4]
_QUALITY = yaml.safe_load((_ROOT / ".github/workflows/_quality.yml").read_text())
_POSTGRES_SELECTION = '-m "not redis and not openfga"'


def test_bare_postgres_lane_selects_only_its_service_posture() -> None:
    """CI and the local entry point exclude the separately provisioned server tests."""
    job = _QUALITY["jobs"]["shifter-platform-tests-postgres"]
    run = next(step["run"] for step in job["steps"] if step.get("name") == "Run application suite against PostgreSQL")
    assert _POSTGRES_SELECTION in run
    assert _POSTGRES_SELECTION in (_ROOT / "Makefile").read_text()
    assert job.get("continue-on-error", False) is False


def test_openfga_job_is_mandatory_for_the_same_platform_changes() -> None:
    """Excluding OpenFGA from the broad lane must preserve its blocking dedicated job."""
    jobs = _QUALITY["jobs"]
    job = jobs["shifter-platform-openfga"]
    assert job["if"] == jobs["shifter-platform-tests-postgres"]["if"]
    assert job.get("continue-on-error", False) is False
    step = next(step for step in job["steps"] if step.get("name") == "Run released OpenFGA conformance")
    assert step["run"] == (
        "./scripts/run_openfga_integration.sh --cov --cov-report=xml:coverage-openfga.xml --cov-fail-under=0"
    )
    assert "if" not in step
    assert step.get("continue-on-error", False) is False
    upload = next(step for step in job["steps"] if step.get("name") == "Upload OpenFGA and native SQL coverage")
    assert upload["with"]["if-no-files-found"] == "error"
    sonar = jobs["sonarcloud"]
    assert "shifter-platform-openfga" in sonar["needs"]
    download = next(step for step in sonar["steps"] if step.get("name") == "Download OpenFGA and native SQL coverage")
    assert download["with"]["name"] == upload["with"]["name"]
    assert "shifter/shifter_platform/coverage-openfga.xml" in (_ROOT / "sonar-project.properties").read_text()


def test_openfga_harness_requires_real_postgres_and_server_configuration() -> None:
    """The dedicated harness cannot pass by skipping unconfigured conformance tests."""
    harness = (_ROOT / "shifter/shifter_platform/scripts/run_openfga_integration.sh").read_text()
    assert "TEST_DB_BACKEND=postgres" in harness
    assert "OPENFGA_INTEGRATION_REQUIRED=1" in harness
    assert "tests/integration/authorization/test_openfga_released_server.py" in harness
