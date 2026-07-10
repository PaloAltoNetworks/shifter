import base64
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "portal-deploy" / "deploy_portal.sh"


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class DeployPortalScriptTests(unittest.TestCase):
    def _install_stubs(
        self,
        root: Path,
        *,
        invalid_bootstrap_emails: bool = False,
        missing_optional_params: bool = False,
        invalid_terminal_param: bool = False,
        invalid_terminal_cap: bool = False,
        zero_workers: bool = False,
        zero_terminal_cap: bool = False,
    ) -> dict[str, str]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        call_log = root / "calls.log"

        _write_executable(
            bin_dir / "aws",
            """
            #!/usr/bin/env bash
            set -euo pipefail
            {
              printf 'aws'
              for arg in "$@"; do printf ' %s' "$arg"; done
              printf '\\n'
            } >> "$CALL_LOG"

            if [[ "$1" == "ssm" && "$2" == "get-parameter" ]]; then
              name=""
              while [[ $# -gt 0 ]]; do
                case "$1" in
                  --name)
                    name="$2"
                    shift 2
                    ;;
                  *)
                    shift
                    ;;
                esac
              done

              case "$name" in
                */image-digest)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'
                  fi
                  ;;
                */environment) printf 'development\\n' ;;
                */image-tag) printf 'abc123\\n' ;;
                */ecr-registry) printf '123456789012.dkr.ecr.us-east-2.amazonaws.com\\n' ;;
                */ecr-repository) printf 'shifter-dev-portal\\n' ;;
                */domain-name) printf 'portal.dev.example.test\\n' ;;
                */s3-bucket) printf 'shifter-dev-bucket\\n' ;;
                */db-secret-arn) printf 'arn:aws:secretsmanager:db\\n' ;;
                */app-secret-arn) printf 'arn:aws:secretsmanager:app\\n' ;;
                */cognito-secret-arn) printf 'arn:aws:secretsmanager:cognito\\n' ;;
                */guacamole-secret-arn)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'arn:aws:secretsmanager:guacamole\\n'
                  fi
                  ;;
                */dc-domain-password-secret-arn)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'arn:aws:secretsmanager:dc\\n'
                  fi
                  ;;
                */guacamole-base-url)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'https://guac.example.test/guacamole\\n'
                  fi
                  ;;
                */guacamole-api-base-url)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'http://guacamole-client:8080/guacamole\\n'
                  fi
                  ;;
                */engine-ecs-cluster-arn) printf 'arn:aws:ecs:cluster/engine\\n' ;;
                */engine-task-definition-arn) printf 'arn:aws:ecs:task-definition/engine:1\\n' ;;
                */engine-ecs-security-group-id) printf 'sg-123\\n' ;;
                */engine-private-subnet-ids) printf 'subnet-a,subnet-b\\n' ;;
                */sqs-cms-url) printf 'https://sqs.example.test/cms\\n' ;;
                */sqs-engine-url) printf 'https://sqs.example.test/engine\\n' ;;
                */sqs-mc-url) printf 'https://sqs.example.test/mc\\n' ;;
                */redis-endpoint)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'redis.example.test\\n'
                  fi
                  ;;
                */channel-layer-backend)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'redis\\n'
                  fi
                  ;;
                */email-backend)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'django.core.mail.backends.smtp.EmailBackend\\n'
                  fi
                  ;;
                */ctf-from-email)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'ctf@example.test\\n'
                  fi
                  ;;
                */platform-bootstrap-staff-emails)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  elif [[ "${INVALID_BOOTSTRAP_EMAILS:-}" == "1" ]]; then
                    printf 'staff example.test\\n'
                  else
                    printf 'staff@example.test,ops@example.test\\n'
                  fi
                  ;;
                */platform-bootstrap-superuser-emails)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf 'admin@example.test\\n'
                  fi
                  ;;
                */portal-web-workers)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  elif [[ "${INVALID_TERMINAL_PARAM:-}" == "1" ]]; then
                    printf '2 -e INJECTED=evil\\n'
                  elif [[ "${ZERO_WORKERS:-}" == "1" ]]; then
                    printf '0\\n'
                  else
                    printf '2\\n'
                  fi
                  ;;
                */terminal-max-sessions-per-user)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf '10\\n'
                  fi
                  ;;
                */terminal-max-sessions)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  elif [[ "${INVALID_TERMINAL_CAP:-}" == "1" ]]; then
                    printf '200 -e INJECTED=evil\\n'
                  elif [[ "${ZERO_TERMINAL_CAP:-}" == "1" ]]; then
                    printf '0\\n'
                  else
                    printf '200\\n'
                  fi
                  ;;
                */terminal-idle-timeout-seconds)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf '1800\\n'
                  fi
                  ;;
                */terminal-max-session-seconds)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf '28800\\n'
                  fi
                  ;;
                */terminal-read-poll-seconds)
                  if [[ "${MISSING_OPTIONAL_PARAMS:-}" == "1" ]]; then
                    printf '\\n'
                  else
                    printf '30\\n'
                  fi
                  ;;
                *) printf '\\n' ;;
              esac
              exit 0
            fi

            printf 'unexpected aws call: %s\\n' "$*" >&2
            exit 1
            """,
        )
        _write_executable(
            bin_dir / "docker",
            """
            #!/usr/bin/env bash
            set -euo pipefail
            {
              printf 'docker'
              for arg in "$@"; do printf ' %s' "$arg"; done
              printf '\\n'
            } >> "$CALL_LOG"

            if [[ "${1:-}" == "stop" || "${1:-}" == "rm" ]]; then
              exit 1
            fi
            exit 0
            """,
        )
        _write_executable(
            bin_dir / "systemctl",
            """
            #!/usr/bin/env bash
            set -euo pipefail
            {
              printf 'systemctl'
              for arg in "$@"; do printf ' %s' "$arg"; done
              printf '\\n'
            } >> "$CALL_LOG"
            exit 0
            """,
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["CALL_LOG"] = str(call_log)
        if invalid_bootstrap_emails:
            env["INVALID_BOOTSTRAP_EMAILS"] = "1"
        if missing_optional_params:
            env["MISSING_OPTIONAL_PARAMS"] = "1"
        if invalid_terminal_param:
            env["INVALID_TERMINAL_PARAM"] = "1"
        if invalid_terminal_cap:
            env["INVALID_TERMINAL_CAP"] = "1"
        if zero_workers:
            env["ZERO_WORKERS"] = "1"
        if zero_terminal_cap:
            env["ZERO_TERMINAL_CAP"] = "1"
        return env

    def _script_args(
        self, root: Path, *, ps_prefix: str = "/shifter/dev/portal"
    ) -> list[str]:
        return [
            str(SCRIPT_PATH),
            "--aws-region",
            "us-east-2",
            "--ps-prefix",
            ps_prefix,
            "--worker-health-monitor-b64",
            _b64("monitor-v1\n"),
            "--worker-health-service-b64",
            _b64("[Service]\nExecStart=/usr/local/bin/shifter-worker-health.sh\n"),
            "--worker-health-timer-b64",
            _b64("[Timer]\nOnCalendar=*:*:00\n"),
            "--worker-health-name-prefix",
            "dev-portal",
            "--worker-health-bin-path",
            str(root / "usr" / "local" / "bin" / "shifter-worker-health.sh"),
            "--worker-health-service-path",
            str(root / "etc" / "systemd" / "system" / "shifter-worker-health.service"),
            "--worker-health-timer-path",
            str(root / "etc" / "systemd" / "system" / "shifter-worker-health.timer"),
            "--worker-health-env-path",
            str(root / "etc" / "shifter-worker-health.env"),
        ]

    def test_missing_required_argument_fails_before_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root)

            result = subprocess.run(
                [str(SCRIPT_PATH)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("--ps-prefix is required", result.stderr)
            self.assertFalse((root / "calls.log").exists())

    def test_rejects_unknown_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root)

            result = subprocess.run(
                [str(SCRIPT_PATH), "--bogus"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown argument: --bogus", result.stderr)
            self.assertFalse((root / "calls.log").exists())

    def test_rejects_invalid_bootstrap_email_before_docker_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root, invalid_bootstrap_emails=True)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid PLATFORM_BOOTSTRAP_STAFF_EMAILS", result.stderr)
            log = (root / "calls.log").read_text(encoding="utf-8")
            self.assertNotIn("docker pull", log)

    def test_deploy_rewrites_worker_health_artifacts_and_tolerates_repeated_runs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root)
            args = self._script_args(root)

            first = subprocess.run(
                args, check=False, capture_output=True, text=True, env=env
            )
            second = subprocess.run(
                args, check=False, capture_output=True, text=True, env=env
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                (root / "usr" / "local" / "bin" / "shifter-worker-health.sh").read_text(
                    encoding="utf-8"
                ),
                "monitor-v1\n",
            )
            self.assertEqual(
                (root / "etc" / "shifter-worker-health.env").read_text(
                    encoding="utf-8"
                ),
                "WH_NAME_PREFIX=dev-portal\n",
            )
            log = (root / "calls.log").read_text(encoding="utf-8")
            self.assertEqual(log.count("docker run -d --name portal"), 2)
            self.assertEqual(log.count("docker run --rm"), 2)
            self.assertLess(
                log.index("docker run --rm"),
                log.index(
                    "docker stop --time 35 portal worker-cms worker-engine worker-mc ctf-scheduler"
                ),
            )
            self.assertIn("python manage.py migrate --noinput", log)
            self.assertIn("SKIP_MIGRATIONS=1", log)
            # ENVIRONMENT must reach the container (config.settings
            # require_environment() fails closed when it is blank, #948).
            self.assertIn("-e ENVIRONMENT=development", log)
            for name in ("worker-cms", "worker-engine", "worker-mc", "ctf-scheduler"):
                self.assertIn(f"docker run -d --name {name}", log)
            self.assertIn("run_worker --queue cms", log)
            self.assertIn("run_worker --queue engine", log)
            self.assertIn("run_worker --queue mc", log)
            self.assertIn("python manage.py run_ctf_scheduler", log)
            self.assertIn(
                "docker stop --time 35 portal worker-cms worker-engine worker-mc ctf-scheduler",
                log,
            )
            self.assertIn(
                "DJANGO_ALLOWED_HOSTS=portal.dev.example.test,localhost,127.0.0.1",
                log,
            )
            self.assertIn("systemctl enable --now shifter-worker-health.timer", log)

    def test_migrate_only_runs_single_migration_without_runtime_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root)

            result = subprocess.run(
                [
                    str(SCRIPT_PATH),
                    "--aws-region",
                    "us-east-2",
                    "--ps-prefix",
                    "/shifter/dev/portal",
                    "--migrate-only",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "calls.log").read_text(encoding="utf-8")
            self.assertIn(
                "docker pull 123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter-dev-portal@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                log,
            )
            self.assertIn("docker run --rm", log)
            self.assertIn("SKIP_MIGRATIONS=1", log)
            self.assertIn("python manage.py migrate --noinput", log)
            self.assertNotIn("docker run -d --name portal", log)
            self.assertNotIn("systemctl", log)

    def test_missing_optional_params_are_not_emitted_as_empty_env_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root, missing_optional_params=True)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "calls.log").read_text(encoding="utf-8")
            self.assertIn(
                "docker pull 123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter-dev-portal:abc123",
                log,
            )
            for name in (
                "GUACAMOLE_SECRET_ARN",
                "GUACAMOLE_BASE_URL",
                "GUACAMOLE_API_BASE_URL",
                "DC_DOMAIN_PASSWORD_SECRET_ARN",
                "REDIS_HOST",
                "CHANNEL_LAYER_BACKEND",
                "CTF_FROM_EMAIL",
                "PLATFORM_BOOTSTRAP_STAFF_EMAILS",
                "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS",
                "PORTAL_WEB_WORKERS",
                "TERMINAL_MAX_SESSIONS",
                "TERMINAL_MAX_SESSIONS_PER_USER",
                "TERMINAL_IDLE_TIMEOUT_SECONDS",
                "TERMINAL_MAX_SESSION_SECONDS",
                "TERMINAL_READ_POLL_SECONDS",
            ):
                self.assertNotIn(f"{name}=", log)
            self.assertIn("EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend", log)

    def test_terminal_capacity_params_emitted_as_docker_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "calls.log").read_text(encoding="utf-8")
            for pair in (
                "PORTAL_WEB_WORKERS=2",
                "TERMINAL_MAX_SESSIONS=200",
                "TERMINAL_MAX_SESSIONS_PER_USER=10",
                "TERMINAL_IDLE_TIMEOUT_SECONDS=1800",
                "TERMINAL_MAX_SESSION_SECONDS=28800",
                "TERMINAL_READ_POLL_SECONDS=30",
            ):
                self.assertIn(pair, log)

    def test_non_numeric_terminal_capacity_param_rejected_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root, invalid_terminal_param=True)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid PORTAL_WEB_WORKERS", result.stderr)
            log_path = root / "calls.log"
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            self.assertNotIn("docker run", log)
            self.assertNotIn("INJECTED=evil", log)

    def test_non_numeric_terminal_cap_rejected_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root, invalid_terminal_cap=True)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid TERMINAL_MAX_SESSIONS", result.stderr)
            log_path = root / "calls.log"
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            self.assertNotIn("docker run", log)
            self.assertNotIn("INJECTED=evil", log)

    def test_zero_portal_web_workers_rejected_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root, zero_workers=True)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Invalid PORTAL_WEB_WORKERS", result.stderr)
            log_path = root / "calls.log"
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            self.assertNotIn("docker run", log)

    def test_zero_terminal_cap_passes_through_as_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root, zero_terminal_cap=True)

            result = subprocess.run(
                self._script_args(root),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "calls.log").read_text(encoding="utf-8")
            self.assertIn("TERMINAL_MAX_SESSIONS=0", log)

    def test_non_dev_allowed_hosts_includes_localhost_aliases(self) -> None:
        # localhost / 127.0.0.1 must be in ALLOWED_HOSTS in every environment:
        # the path-scoped HealthCheckMiddleware (#477) rewrites the Host of
        # /health probes to "localhost", so the ALB / Docker health checks are
        # only admitted when localhost is allowed. Excluding it for non-dev
        # fails the portal target group health check closed (DisallowedHost ->
        # 400 -> unhealthy -> 504). Matches scripts/gcp/render_runtime_env.py.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._install_stubs(root)

            result = subprocess.run(
                self._script_args(root, ps_prefix="/shifter/prod/portal"),
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "calls.log").read_text(encoding="utf-8")
            self.assertIn(
                "DJANGO_ALLOWED_HOSTS=portal.dev.example.test,localhost,127.0.0.1",
                log,
            )
