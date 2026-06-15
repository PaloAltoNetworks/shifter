"""CLI arg parsing -> validated RunConfig, and the secrets-off-argv guarantee."""

import pytest

from event_load_harness.cli import build_parser, config_from_args


def _parse(argv):
    return build_parser().parse_args(argv)


def test_flags_build_a_valid_config():
    args = _parse(
        [
            "--target-url",
            "https://dev.example.com",
            "--environment",
            "dev",
            "--concurrency",
            "25",
            "--ramp-seconds",
            "10",
            "--duration-seconds",
            "60",
            "--actor-source",
            "dev-login",
            "--actor-count",
            "25",
            "--confirm-host",
            "dev.example.com",
            "--report-path",
            "out/envelope.md",
        ]
    )
    cfg = config_from_args(args)
    assert cfg.target_url == "https://dev.example.com"
    assert cfg.concurrency == 25
    assert cfg.profile == "portal-core"  # default applied
    assert cfg.metric_source == "client-only"  # default applied


def test_config_file_is_loaded(tmp_path):
    p = tmp_path / "run.toml"
    p.write_text(
        'target_url = "https://dev.example.com"\n'
        'environment = "dev"\n'
        'profile = "portal-core"\n'
        "concurrency = 40\n"
        "ramp_seconds = 5\n"
        "duration_seconds = 30\n"
        'actor_source = "dev-login"\n'
        'metric_source = "client-only"\n'
        'report_path = "out/envelope.md"\n'
        'confirm_host = "dev.example.com"\n'
    )
    cfg = config_from_args(_parse(["--config", str(p)]))
    assert cfg.concurrency == 40


def test_cli_flag_overrides_config_file(tmp_path):
    p = tmp_path / "run.toml"
    p.write_text(
        'target_url = "https://dev.example.com"\n'
        'environment = "dev"\n'
        "concurrency = 40\n"
        "ramp_seconds = 5\n"
        "duration_seconds = 30\n"
        'actor_source = "dev-login"\n'
        'report_path = "out/envelope.md"\n'
        'confirm_host = "dev.example.com"\n'
    )
    cfg = config_from_args(_parse(["--config", str(p), "--concurrency", "99"]))
    assert cfg.concurrency == 99


def test_parser_exposes_no_secret_bearing_option():
    # Secrets must come from the 0600 manifest, never from argv (visible to other
    # process readers and shell history).
    help_text = build_parser().format_help().lower()
    for forbidden in ("--password", "--token", "--secret", "--cookie", "--session"):
        assert forbidden not in help_text


def test_aws_target_ids_collected_into_config(tmp_path):
    args = _parse(
        [
            "--target-url",
            "https://dev.example.com",
            "--environment",
            "dev",
            "--concurrency",
            "5",
            "--ramp-seconds",
            "0",
            "--duration-seconds",
            "10",
            "--actor-source",
            "dev-login",
            "--metric-source",
            "aws",
            "--region",
            "us-east-2",
            "--aws-alb",
            "app/portal/abc",
            "--confirm-host",
            "dev.example.com",
            "--report-path",
            "out/e.md",
        ]
    )
    cfg = config_from_args(args)
    assert cfg.metric_source == "aws"
    assert cfg.extra["aws_targets"]["alb"] == "app/portal/abc"


def test_invalid_config_surfaces_as_config_error():
    from event_load_harness.config import ConfigError

    args = _parse(
        [
            "--target-url",
            "http://dev.example.com",  # not https
            "--environment",
            "dev",
            "--concurrency",
            "5",
            "--ramp-seconds",
            "0",
            "--duration-seconds",
            "10",
            "--actor-source",
            "dev-login",
            "--report-path",
            "out/e.md",
        ]
    )
    with pytest.raises(ConfigError):
        config_from_args(args)
