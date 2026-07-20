"""AWS account bootstrap operations for the Shifter deployment CLI."""

import json
import os
import subprocess  # nosec B404
import sys
import uuid
from pathlib import Path

import terraform_backend as tb
from bootstrap_core import (
    BootstrapConfig,
    _validate_argv,
    confirm,
    error,
    get_aws_account_id,
    get_repo_root,
    header,
    info,
    run_cmd,
    success,
    warn,
)


def s3_bucket_exists(bucket_name: str, profile: str) -> bool:
    """Check if an S3 bucket exists."""
    cmd = ["aws", "--profile", profile, "s3api", "head-bucket", "--bucket", bucket_name]
    _validate_argv(cmd)
    result = subprocess.run(  # nosec B603 B607
        cmd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def dynamodb_table_exists(table_name: str, region: str, profile: str) -> bool:
    """Check if a DynamoDB table exists."""
    result = subprocess.run(  # nosec B603 B607
        [
            "aws",
            "--profile",
            profile,
            "dynamodb",
            "describe-table",
            "--table-name",
            table_name,
            "--region",
            region,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def github_secret_exists(secret_name: str, github_org: str, github_repo: str) -> bool:
    """Check if a GitHub secret exists."""
    result = subprocess.run(  # nosec B603 B607
        ["gh", "secret", "list", "--repo", f"{github_org}/{github_repo}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout is not None and secret_name in result.stdout


def create_s3_bucket(bucket_name: str, region: str, profile: str, dry_run: bool) -> None:
    """Create and configure an S3 bucket for Terraform state."""
    run_cmd(
        [
            "aws",
            "s3api",
            "create-bucket",
            "--bucket",
            bucket_name,
            "--region",
            region,
            "--create-bucket-configuration",
            f"LocationConstraint={region}",
        ],
        dry_run=dry_run,
        profile=profile,
    )

    run_cmd(
        [
            "aws",
            "s3api",
            "put-bucket-versioning",
            "--bucket",
            bucket_name,
            "--versioning-configuration",
            "Status=Enabled",
        ],
        dry_run=dry_run,
        profile=profile,
    )

    run_cmd(
        [
            "aws",
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket_name,
            "--server-side-encryption-configuration",
            '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}',
        ],
        dry_run=dry_run,
        profile=profile,
    )

    run_cmd(
        [
            "aws",
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket_name,
            "--public-access-block-configuration",
            (
                '{"BlockPublicAcls": true, "IgnorePublicAcls": true, '
                '"BlockPublicPolicy": true, "RestrictPublicBuckets": true}'
            ),
        ],
        dry_run=dry_run,
        profile=profile,
    )


def create_dynamodb_table(table_name: str, region: str, profile: str, dry_run: bool) -> None:
    """Create a DynamoDB table for Terraform state locking."""
    run_cmd(
        [
            "aws",
            "dynamodb",
            "create-table",
            "--table-name",
            table_name,
            "--attribute-definitions",
            "AttributeName=LockID,AttributeType=S",
            "--key-schema",
            "AttributeName=LockID,KeyType=HASH",
            "--billing-mode",
            "PAY_PER_REQUEST",
            "--region",
            region,
        ],
        dry_run=dry_run,
        profile=profile,
    )

    if not dry_run:
        info("Waiting for table to be active...")
        run_cmd(
            ["aws", "dynamodb", "wait", "table-exists", "--table-name", table_name, "--region", region],
            profile=profile,
        )


def administrator_access_policy_document() -> str:
    """Return the inline administrator policy used for bootstrap and CI roles.

    Some AWS organizations deny iam:AttachRolePolicy via SCP while still
    allowing inline role policies. The effective policy matches AWS managed
    AdministratorAccess without depending on managed-policy attachment APIs.
    """
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "*",
                    "Resource": "*",
                }
            ],
        }
    )


AWS_ENVIRONMENTS = ("dev", "proof", "prod")


def _ensure_state_bucket(bucket_name: str, config: BootstrapConfig, profile: str, dry_run: bool) -> None:
    """Create the Terraform-state S3 bucket, or confirm reuse if it already exists."""
    if not dry_run and s3_bucket_exists(bucket_name, profile):
        warn(f"S3 bucket '{bucket_name}' already exists")
        if not confirm("Continue using existing bucket?"):
            error("Cannot continue without S3 bucket for Terraform state")
            sys.exit(1)
        info("Using existing bucket")
    else:
        create_s3_bucket(bucket_name, config.region, profile, dry_run)


def _run_iam_terraform(config: BootstrapConfig, bucket_name: str, account_id: str, profile: str, dry_run: bool) -> str:
    """Run the global/iam Terraform stack and return the production GitHub Actions role ARN."""
    repo_root = get_repo_root()
    iam_tf_dir = repo_root / "platform" / "terraform" / "global" / "iam"

    if not iam_tf_dir.exists():
        error(f"IAM Terraform directory not found: {iam_tf_dir}")
        sys.exit(1)

    # Write per-instance backend config outside the product repo.
    instance_dir = tb.instance_dir_from_env() or Path.home() / ".shifter" / f"{config.env}-{bucket_name}"
    backend_dir = tb.resolve_instance_backend_dir(
        env=config.env,
        bucket=bucket_name,
        instance_dir=instance_dir,
    )
    backend_config_file = tb.backend_config_for_stack(backend_dir, "global/iam", config.env)
    if not dry_run:
        tb.write_instance_backend_configs(
            backend_dir=backend_dir,
            env=config.env,
            bucket=bucket_name,
            region=config.region,
        )
        info("Using rendered instance backend config for global/iam")
        success(f"Backend config ready for {config.env}")
    else:
        info("[DRY-RUN] Would write instance backend config outside the product repo")

    original_dir = os.getcwd()
    os.chdir(iam_tf_dir)

    # Set AWS_PROFILE for Terraform (only affects this process and its children)
    os.environ["AWS_PROFILE"] = profile

    try:
        info("Running terraform init with instance backend config")
        run_cmd(
            ["terraform", "init", "-reconfigure", f"-backend-config={backend_config_file}"],
            dry_run=dry_run,
        )
        _terraform_apply_iam(config, dry_run)
        role_arn = _terraform_iam_role_arn(config, account_id, dry_run)
    finally:
        os.chdir(original_dir)

    return role_arn


def _terraform_apply_iam(config: BootstrapConfig, dry_run: bool) -> None:
    """Run terraform apply (or plan in dry-run) for the IAM stack; exit on apply failure."""
    info(f"Running terraform apply for {config.env}...")
    tfvars_file = f"{config.env}.tfvars"

    if dry_run:
        run_cmd(["terraform", "plan", f"-var-file={tfvars_file}"], dry_run=dry_run)
        return

    apply_result = run_cmd(
        ["terraform", "apply", "-auto-approve", f"-var-file={tfvars_file}"],
        dry_run=dry_run,
        check=False,
    )
    if apply_result and apply_result.returncode != 0:
        error("Terraform apply failed for IAM module")
        error("The bootstrap role is still active - you can retry manually")
        sys.exit(1)


def _terraform_iam_role_arn(config: BootstrapConfig, account_id: str, dry_run: bool) -> str:
    """Return the production GitHub Actions role ARN from terraform output (synthetic in dry-run)."""
    if dry_run:
        return f"arn:aws:iam::{account_id}:role/{config.role_name}"

    result = subprocess.run(  # nosec B603 B607
        ["terraform", "output", "-raw", "github_actions_role_arn"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error("Failed to get role ARN from Terraform output")
        sys.exit(1)
    role_arn = result.stdout.strip()
    success("Production IAM role created")
    return role_arn


def _bootstrap_account_id(profile: str, dry_run: bool) -> str:
    """Resolve the active AWS account id, using a stable synthetic id in dry-run mode."""
    if not dry_run:
        account_id = get_aws_account_id(profile)
        info(f"AWS Account ID: {account_id}")
        return account_id
    info("[DRY-RUN] Would get AWS account ID")
    return "123456789012"


def _bootstrap_state_bucket_name(config: BootstrapConfig) -> str:
    """Return the unique bootstrap state bucket name for this run."""
    return f"{config.bucket_prefix}-{uuid.uuid4()}"


def _github_oidc_trust_policy(config: BootstrapConfig, account_id: str) -> dict[str, object]:
    """Build the GitHub Actions OIDC trust policy for the temporary role."""
    oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": oidc_arn},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": (f"repo:{config.github_org}/{config.github_repo}:*")
                    },
                },
            }
        ],
    }


def _create_bootstrap_role(
    config: BootstrapConfig,
    *,
    account_id: str,
    profile: str,
    dry_run: bool,
) -> None:
    """Create the temporary bootstrap IAM role and inline admin policy."""
    info(f"Creating temporary bootstrap role: {config.bootstrap_role_name}")
    info("This role will be deleted after Terraform creates the production role")

    run_cmd(
        [
            "aws",
            "iam",
            "create-role",
            "--role-name",
            config.bootstrap_role_name,
            "--assume-role-policy-document",
            json.dumps(_github_oidc_trust_policy(config, account_id)),
            "--tags",
            f"Key=Name,Value={config.bootstrap_role_name}",
            "Key=Project,Value=shifter",
            "Key=Purpose,Value=bootstrap-temporary",
        ],
        dry_run=dry_run,
        check=False,
        profile=profile,
    )
    run_cmd(
        [
            "aws",
            "iam",
            "put-role-policy",
            "--role-name",
            config.bootstrap_role_name,
            "--policy-name",
            "bootstrap-administrator-access",
            "--policy-document",
            administrator_access_policy_document(),
        ],
        dry_run=dry_run,
        profile=profile,
    )
    success("Bootstrap IAM role created with AdministratorAccess")


def _delete_bootstrap_role(config: BootstrapConfig, *, profile: str, dry_run: bool) -> None:
    """Delete the temporary bootstrap role after Terraform creates the production role."""
    info(f"Deleting temporary bootstrap role: {config.bootstrap_role_name}")
    run_cmd(
        [
            "aws",
            "iam",
            "delete-role-policy",
            "--role-name",
            config.bootstrap_role_name,
            "--policy-name",
            "bootstrap-administrator-access",
        ],
        dry_run=dry_run,
        check=False,
        profile=profile,
    )
    run_cmd(
        [
            "aws",
            "iam",
            "delete-role",
            "--role-name",
            config.bootstrap_role_name,
        ],
        dry_run=dry_run,
        check=False,
        profile=profile,
    )
    success("Bootstrap role deleted - using Terraform-managed role going forward")


def _ensure_ebs_encryption_by_default(config: BootstrapConfig, profile: str, dry_run: bool) -> None:
    """Enable account-level EBS encryption-by-default in the deploy region.

    The range provisioner's RunInstances grant requires encrypted root volumes
    (``ec2:Encrypted=true``). Without account-default encryption, range launches
    from the unencrypted base and scenario AMIs are denied and no range can
    provision. Idempotent: only enables when currently disabled.
    """
    if dry_run:
        info(f"[DRY-RUN] Would ensure EBS encryption-by-default in {config.region}")
        return
    check = [
        "aws",
        "--profile",
        profile,
        "--region",
        config.region,
        "ec2",
        "get-ebs-encryption-by-default",
        "--query",
        "EbsEncryptionByDefault",
        "--output",
        "text",
    ]
    _validate_argv(check)
    result = subprocess.run(check, capture_output=True, text=True)  # nosec B603 B607
    if result.returncode == 0 and result.stdout.strip() == "True":
        info("EBS encryption-by-default already enabled")
        return
    run_cmd(
        ["aws", "--profile", profile, "--region", config.region, "ec2", "enable-ebs-encryption-by-default"],
        dry_run=dry_run,
    )
    success("EBS encryption-by-default enabled")


def bootstrap_account(config: BootstrapConfig, profile: str, dry_run: bool = False) -> dict[str, object]:
    """Bootstrap AWS account with state backend and IAM role."""
    header(f"Bootstrapping {config.env.upper()} AWS Account")

    info(f"Using AWS Profile: {profile}")
    account_id = _bootstrap_account_id(profile, dry_run)
    bucket_name = _bootstrap_state_bucket_name(config)

    info(f"S3 Bucket: {bucket_name}")
    info("State locking: S3 native (use_lockfile = true) — no DynamoDB needed")
    info(f"IAM Role: {config.role_name}")

    if not dry_run and not confirm("Create these resources?"):
        warn("Aborted by user")
        sys.exit(0)

    # Step 1: S3 Bucket
    header("Step 1/3: Creating S3 Bucket")
    _ensure_state_bucket(bucket_name, config, profile, dry_run)
    success("S3 bucket ready")

    # Account hardening: EBS encryption-by-default. Range provisioning fails
    # closed without it (the provisioner's RunInstances grant requires
    # ec2:Encrypted=true on range root volumes).
    _ensure_ebs_encryption_by_default(config, profile, dry_run)

    # Step 2: Bootstrap IAM Role (temporary - will be replaced by Terraform)
    header("Step 2/3: Creating Bootstrap IAM Role")
    _create_bootstrap_role(config, account_id=account_id, profile=profile, dry_run=dry_run)

    # Step 3: Run Terraform to create OIDC provider and production IAM role
    header("Step 3/3: Creating OIDC Provider and IAM Role via Terraform")

    info("Running Terraform to create properly scoped IAM policies...")
    info("The production role will be: " + config.role_name)
    role_arn = _run_iam_terraform(config, bucket_name, account_id, profile, dry_run)

    # Cleanup: Delete the bootstrap role
    header("Cleanup: Removing Bootstrap Role")
    _delete_bootstrap_role(config, profile=profile, dry_run=dry_run)

    return {
        "bucket_name": bucket_name,
        "role_arn": role_arn,
        "region": config.region,
        "env": config.env,
        "secret_name": config.secret_name,
        "state_bucket_secret_name": config.state_bucket_secret_name,
        "github_org": config.github_org,
        "github_repo": config.github_repo,
    }
