"""Per-range AWS Polaris agent Bedrock role configuration (#1377).

Depends on the ``_env`` leaf only.
"""

import os
import re
from dataclasses import dataclass

from ._env import _get_int_env, _parse_csv_env


@dataclass(frozen=True)
class AWSPolarisAgentConfig:
    """Per-range AWS Polaris agent Bedrock role config seam (#1377).

    One validated profile for the AWS Polaris a14-kali agent: the STS/Bedrock
    region, the approved main and small/fast Bedrock model ids, the exact
    inference-profile ARNs those model ids resolve through, the backing
    foundation-model ARNs the profiles invoke (potentially across regions
    for cross-region inference), and the STS session lifecycle used to
    refresh the per-range agent role's short-lived credentials.

    Both the per-range Terraform agent-role policy and
    ``PolarisRangeBootstrapPlan`` are meant to consume this seam so model and
    ARN defaults live in exactly one place instead of independently in IAM,
    Python, embedded shell, and deployment Terraform. Holds only non-secret
    references (region, model ids, ARNs, durations) -- never a credential,
    session token, or access key. The per-range target role ARN itself is
    not part of this static config; Terraform supplies it at apply time.
    """

    region: str
    main_model_id: str
    small_model_id: str
    main_inference_profile_arn: str
    small_inference_profile_arn: str
    main_backing_model_arns: tuple[str, ...]
    small_backing_model_arns: tuple[str, ...]
    # REQUIRED (non-empty) whenever this config is present. The seam's
    # enablement signal is main_inference_profile_arn: once that is set, an
    # enabled per-range Bedrock agent role must always carry a permissions
    # boundary (ADR-004-R21) -- there is no "enabled but no boundary" state.
    permissions_boundary_arn: str
    sts_session_duration_seconds: int = 900
    refresh_window_seconds: int = 300


# Bedrock model ids for the a14-kali agent's default Bedrock plane. Reused
# verbatim from the values PolarisRangeBootstrapPlan previously carried as
# its own independent module-level defaults, so the two stop drifting apart
# (#1377 seam consolidation).
_AWS_POLARIS_AGENT_DEFAULT_MAIN_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
_AWS_POLARIS_AGENT_DEFAULT_SMALL_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# arn:aws:bedrock:<region>:<account-or-empty>:inference-profile/<id> or
# arn:aws:bedrock:<region>:<account-or-empty>:foundation-model/<id>. Account
# is empty for foundation-model ARNs.
_BEDROCK_ARN_PATTERN = re.compile(
    r"^arn:aws:bedrock:[a-z0-9-]+:\d*:(?:inference-profile|foundation-model)/[A-Za-z0-9._:/-]+$"
)
# arn:aws:iam::<account>:policy/<name>. The permissions boundary must be an
# IAM *policy* ARN specifically -- a role/user/group ARN is not a valid
# permissions-boundary target even though it would match a generic IAM ARN
# shape.
_IAM_ARN_PATTERN = re.compile(r"^arn:aws:iam::\d{12}:policy/[A-Za-z0-9._/-]+$")

# Plain AWS region shape (e.g. "us-east-2", "ap-southeast-1"). region is
# substituted verbatim into a double-quoted shell variable assignment in the
# root-executed SSM range bootstrap scripts (PolarisRangeBootstrapPlan); a
# value carrying a quote, `$()`, backtick, or other shell metacharacter would
# escape that assignment and run as root at next provision, so this
# allowlists the exact region shape instead of merely checking presence
# (#1377 codex pre-push finding: command injection into root-executed shell).
_AWS_REGION_PATTERN = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")

# Bedrock model / inference-profile id shape (e.g.
# "us.anthropic.claude-sonnet-4-6", "anthropic.claude-haiku-4-5-v1:0").
# main_model_id/small_model_id have the same root-executed-shell substitution
# exposure as region above; only blankness was previously checked.
_BEDROCK_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


def _missing_aws_polaris_agent_env(
    *,
    region: str,
    small_inference_profile_arn: str,
    main_backing_model_arns: tuple[str, ...],
    small_backing_model_arns: tuple[str, ...],
    permissions_boundary_arn: str,
) -> list[str]:
    """Return display names for missing required AWS Polaris agent settings."""
    return [
        name
        for name, value in (
            ("AWS_POLARIS_AGENT_REGION", region),
            ("AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN", small_inference_profile_arn),
            ("AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS", main_backing_model_arns),
            ("AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS", small_backing_model_arns),
            ("AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN", permissions_boundary_arn),
        )
        if not value
    ]


def _validate_aws_polaris_agent_region(region: str) -> None:
    """Fail closed on a region that is not a plain AWS region string."""
    if not _AWS_REGION_PATTERN.match(region):
        raise RuntimeError(
            f"AWS_POLARIS_AGENT_REGION is not a valid AWS region (expected e.g. 'us-east-2'): {region!r}"
        )


def _validate_aws_polaris_agent_model_id(env_name: str, model_id: str) -> None:
    """Fail closed on a Bedrock model/inference id containing shell metacharacters."""
    if not _BEDROCK_MODEL_ID_PATTERN.match(model_id):
        raise RuntimeError(
            f"{env_name} is not a valid Bedrock model id (expected e.g. 'us.anthropic.claude-sonnet-4-6'): {model_id!r}"
        )


def _validate_aws_polaris_agent_arns(
    *,
    main_inference_profile_arn: str,
    small_inference_profile_arn: str,
    main_backing_model_arns: tuple[str, ...],
    small_backing_model_arns: tuple[str, ...],
    permissions_boundary_arn: str,
) -> None:
    """Fail closed on any ARN that does not look like a real Bedrock/IAM ARN."""
    for env_name, arn in (
        ("AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN", main_inference_profile_arn),
        ("AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN", small_inference_profile_arn),
        *(("AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS", arn) for arn in main_backing_model_arns),
        *(("AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS", arn) for arn in small_backing_model_arns),
    ):
        if not _BEDROCK_ARN_PATTERN.match(arn):
            raise RuntimeError(f"{env_name} is not a valid Bedrock ARN (expected arn:aws:bedrock:...): {arn!r}")

    if not _IAM_ARN_PATTERN.match(permissions_boundary_arn):
        raise RuntimeError(
            "AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN is not a valid IAM policy ARN "
            f"(expected arn:aws:iam::<account>:policy/...): {permissions_boundary_arn!r}"
        )


def _validate_aws_polaris_agent_sts_timing(*, sts_session_duration_seconds: int, refresh_window_seconds: int) -> None:
    """Fail closed on an STS session/refresh pairing that can't refresh before expiry."""
    if sts_session_duration_seconds < 900:
        raise RuntimeError(
            "AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS must be >= 900 (AWS AssumeRole minimum session duration)"
        )
    if refresh_window_seconds >= sts_session_duration_seconds:
        raise RuntimeError(
            "AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS must be less than "
            "AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS so the host refreshes before expiry"
        )


def load_aws_polaris_agent_config() -> AWSPolarisAgentConfig | None:
    """Load the per-range AWS Polaris agent Bedrock role config, when configured.

    Single seam (#1377) for the AWS Polaris a14-kali agent's region, approved
    main/small Bedrock model ids, their exact inference-profile and backing
    foundation-model ARNs, and STS session lifecycle. The per-range Terraform
    agent-role policy and ``PolarisRangeBootstrapPlan`` are meant to consume
    this instead of keeping independent model/ARN defaults.

    Returns:
        The validated config, or ``None`` when
        ``AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN`` is unset -- this
        environment has not enabled the per-range Bedrock agent role yet.

    Raises:
        RuntimeError: The seam is enabled (main inference-profile ARN set)
            but a required field is missing (including the permissions
            boundary ARN -- ADR-004-R21 requires an enabled agent role to
            always carry one), a model id is blank or contains a shell
            metacharacter, the region is not a plain AWS region string, an
            ARN does not look like a Bedrock/IAM policy ARN, the STS session
            duration is below AWS's 900-second ``AssumeRole`` floor, or the
            refresh window would not leave time to refresh before expiry.
    """
    main_inference_profile_arn = os.environ.get("AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN", "").strip()
    if not main_inference_profile_arn:
        return None

    region = os.environ.get("AWS_POLARIS_AGENT_REGION", "").strip()
    small_inference_profile_arn = os.environ.get("AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN", "").strip()
    main_backing_model_arns = _parse_csv_env(os.environ.get("AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS", ""))
    small_backing_model_arns = _parse_csv_env(os.environ.get("AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS", ""))
    # REQUIRED whenever the seam is enabled (ADR-004-R21): an enabled
    # per-range Bedrock agent role must always carry a permissions boundary,
    # not fall back to a conditional/null boundary downstream in Terraform.
    permissions_boundary_arn = os.environ.get("AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN", "").strip()

    missing = _missing_aws_polaris_agent_env(
        region=region,
        small_inference_profile_arn=small_inference_profile_arn,
        main_backing_model_arns=main_backing_model_arns,
        small_backing_model_arns=small_backing_model_arns,
        permissions_boundary_arn=permissions_boundary_arn,
    )
    if missing:
        raise RuntimeError("Missing required AWS Polaris agent configuration: " + ", ".join(missing))

    _validate_aws_polaris_agent_region(region)

    # Absent env var -> reuse the existing hardcoded default (previously
    # duplicated as a PolarisRangeBootstrapPlan module constant). Present but
    # blank -> an explicit misconfiguration; fail closed rather than silently
    # falling back to the default.
    main_model_id_raw = os.environ.get("AWS_POLARIS_AGENT_MAIN_MODEL_ID")
    main_model_id = main_model_id_raw if main_model_id_raw is not None else _AWS_POLARIS_AGENT_DEFAULT_MAIN_MODEL_ID
    small_model_id_raw = os.environ.get("AWS_POLARIS_AGENT_SMALL_MODEL_ID")
    small_model_id = small_model_id_raw if small_model_id_raw is not None else _AWS_POLARIS_AGENT_DEFAULT_SMALL_MODEL_ID
    if not main_model_id.strip():
        raise RuntimeError("AWS_POLARIS_AGENT_MAIN_MODEL_ID must not be blank")
    if not small_model_id.strip():
        raise RuntimeError("AWS_POLARIS_AGENT_SMALL_MODEL_ID must not be blank")
    _validate_aws_polaris_agent_model_id("AWS_POLARIS_AGENT_MAIN_MODEL_ID", main_model_id)
    _validate_aws_polaris_agent_model_id("AWS_POLARIS_AGENT_SMALL_MODEL_ID", small_model_id)

    _validate_aws_polaris_agent_arns(
        main_inference_profile_arn=main_inference_profile_arn,
        small_inference_profile_arn=small_inference_profile_arn,
        main_backing_model_arns=main_backing_model_arns,
        small_backing_model_arns=small_backing_model_arns,
        permissions_boundary_arn=permissions_boundary_arn,
    )

    sts_session_duration_seconds = _get_int_env("AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS", 900)
    refresh_window_seconds = _get_int_env("AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS", 300)
    _validate_aws_polaris_agent_sts_timing(
        sts_session_duration_seconds=sts_session_duration_seconds,
        refresh_window_seconds=refresh_window_seconds,
    )

    return AWSPolarisAgentConfig(
        region=region,
        main_model_id=main_model_id,
        small_model_id=small_model_id,
        main_inference_profile_arn=main_inference_profile_arn,
        small_inference_profile_arn=small_inference_profile_arn,
        main_backing_model_arns=main_backing_model_arns,
        small_backing_model_arns=small_backing_model_arns,
        permissions_boundary_arn=permissions_boundary_arn,
        sts_session_duration_seconds=sts_session_duration_seconds,
        refresh_window_seconds=refresh_window_seconds,
    )
