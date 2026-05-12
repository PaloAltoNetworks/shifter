#!/usr/bin/env python3
"""One-shot setup for the end-of-game Claude cutoff Lambda.

Creates:
  - Secrets Manager secret with the CTFd admin token
  - IAM role for the Lambda (minimal perms)
  - Lambda function
  - EventBridge Scheduler schedule (DISABLED by default)

The schedule starts DISABLED so we can manually invoke the Lambda in dry-run
mode first, verify the output, then enable.

Usage:
  export AWS_PROFILE=panw-shifter-dev-workstation
  export CTFD_TOKEN=<admin token, 48h expiry>
  python3 scripts/polaris-aws-range/setup_claude_cutoff.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-2"
LAMBDA_NAME = "polaris-claude-cutoff"
ROLE_NAME = "polaris-claude-cutoff-lambda"
SECRET_NAME = "polaris/claude-ops-token"
SCHEDULE_NAME = "polaris-claude-cutoff-15min"
SCHEDULE_GROUP = "default"

# Schedule stops at event end + 24h buffer
SCHEDULE_END_UTC = "2026-04-19T04:00:00Z"

HERE = Path(__file__).resolve().parent
LAMBDA_SRC = HERE / "claude_cutoff_lambda.py"

session = boto3.Session(region_name=REGION)
iam = session.client("iam")
lam = session.client("lambda")
ec2 = session.client("ec2")
events = session.client("scheduler")
sm = session.client("secretsmanager")


def ensure_secret(token: str) -> str:
    try:
        resp = sm.describe_secret(SecretId=SECRET_NAME)
        arn = resp["ARN"]
        sm.put_secret_value(SecretId=arn, SecretString=token)
        print(f"secret updated: {arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        resp = sm.create_secret(Name=SECRET_NAME, SecretString=token,
                                 Description="CTFd admin token for polaris claude-cutoff Lambda")
        arn = resp["ARN"]
        print(f"secret created: {arn}")
    return arn


def ensure_role(secret_arn: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    try:
        iam.get_role(RoleName=ROLE_NAME)
        print(f"role exists: {ROLE_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Polaris end-of-game Claude cutoff Lambda",
        )
        print(f"role created: {ROLE_NAME}")

    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )

    inline = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadCtfdToken",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [secret_arn],
            },
            {
                "Sid": "EC2Lookup",
                "Effect": "Allow",
                "Action": ["ec2:DescribeInstances"],
                "Resource": "*",
            },
            {
                "Sid": "EC2Tag",
                "Effect": "Allow",
                "Action": ["ec2:CreateTags"],
                "Resource": "arn:aws:ec2:*:*:instance/*",
                "Condition": {
                    "StringEquals": {"aws:ResourceTag/Name": "kali"},
                },
            },
            {
                "Sid": "SSMRunCommand",
                "Effect": "Allow",
                "Action": [
                    "ssm:SendCommand",
                    "ssm:GetCommandInvocation",
                    "ssm:ListCommandInvocations",
                ],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="inline",
        PolicyDocument=json.dumps(inline),
    )
    return iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lambda_function.py", LAMBDA_SRC.read_text())
    return buf.getvalue()


def ensure_lambda(role_arn: str) -> str:
    code = build_zip()
    env = {
        "CTFD_URL": "https://polaris.example.com",
        "CTFD_TOKEN_SECRET_ID": SECRET_NAME,
        "DRY_RUN": "1",   # start in dry-run
        "KEEP_CLAUDE": "",
    }
    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=code)
        # wait for the update to finish before touching config
        waiter = lam.get_waiter("function_updated")
        waiter.wait(FunctionName=LAMBDA_NAME)
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Role=role_arn,
            Handler="lambda_function.handler",
            Runtime="python3.12",
            Timeout=300,
            MemorySize=256,
            Environment={"Variables": env},
        )
        print(f"lambda updated: {LAMBDA_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        # role propagation can lag; retry a few times
        for attempt in range(10):
            try:
                lam.create_function(
                    FunctionName=LAMBDA_NAME,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler="lambda_function.handler",
                    Code={"ZipFile": code},
                    Timeout=300,
                    MemorySize=256,
                    Environment={"Variables": env},
                    Description="Polaris end-of-game Claude cutoff",
                )
                break
            except ClientError as ce:
                if "cannot be assumed" in str(ce) and attempt < 9:
                    time.sleep(5)
                    continue
                raise
        print(f"lambda created: {LAMBDA_NAME}")
    return lam.get_function(FunctionName=LAMBDA_NAME)["Configuration"]["FunctionArn"]


def ensure_scheduler_role(lambda_arn: str) -> str:
    role = "polaris-claude-cutoff-scheduler"
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "scheduler.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    try:
        iam.get_role(RoleName=role)
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(RoleName=role,
                        AssumeRolePolicyDocument=json.dumps(trust),
                        Description="Invoke polaris-claude-cutoff Lambda")

    iam.put_role_policy(
        RoleName=role, PolicyName="inline",
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": [lambda_arn, lambda_arn + ":*"],
            }],
        }),
    )
    return iam.get_role(RoleName=role)["Role"]["Arn"]


def ensure_schedule(lambda_arn: str, scheduler_role_arn: str) -> str:
    target = {
        "Arn": lambda_arn,
        "RoleArn": scheduler_role_arn,
        "Input": json.dumps({"source": "eventbridge-scheduler"}),
    }
    common = {
        "ScheduleExpression": "rate(15 minutes)",
        "State": "DISABLED",   # start disabled — operator enables after dry-run
        "Target": target,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Description": "Polaris: check CTFd every 15min for Bunker-clearing operators and retire their Claude",
        "EndDate": SCHEDULE_END_UTC,
    }
    try:
        events.update_schedule(Name=SCHEDULE_NAME, GroupName=SCHEDULE_GROUP, **common)
        print(f"schedule updated: {SCHEDULE_NAME} (DISABLED)")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        events.create_schedule(Name=SCHEDULE_NAME, GroupName=SCHEDULE_GROUP, **common)
        print(f"schedule created: {SCHEDULE_NAME} (DISABLED)")


def main() -> int:
    token = os.environ.get("CTFD_TOKEN")
    if not token:
        print("ERROR: set CTFD_TOKEN env var to a CTFd admin token with >= 48h TTL", file=sys.stderr)
        return 1

    secret_arn = ensure_secret(token)
    role_arn = ensure_role(secret_arn)
    time.sleep(5)  # role propagation
    lambda_arn = ensure_lambda(role_arn)
    scheduler_role_arn = ensure_scheduler_role(lambda_arn)
    time.sleep(3)
    ensure_schedule(lambda_arn, scheduler_role_arn)

    print()
    print("=== setup complete ===")
    print(f"  lambda:   {lambda_arn}")
    print(f"  schedule: arn:aws:scheduler:{REGION}:*:schedule/{SCHEDULE_GROUP}/{SCHEDULE_NAME}")
    print()
    print("Next steps:")
    print(f"  1. Invoke in dry-run:")
    print(f"     aws --region {REGION} lambda invoke --function-name {LAMBDA_NAME} /tmp/out.json")
    print(f"     cat /tmp/out.json")
    print(f"  2. When happy, flip DRY_RUN=0 and enable the schedule:")
    print(f"     aws --region {REGION} lambda update-function-configuration --function-name {LAMBDA_NAME} "
          f"--environment 'Variables={{CTFD_URL=https://polaris.example.com,"
          f"CTFD_TOKEN_SECRET_ID={SECRET_NAME},DRY_RUN=0,KEEP_CLAUDE=}}'")
    print(f"     aws --region {REGION} scheduler update-schedule --name {SCHEDULE_NAME} ... --state ENABLED ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
