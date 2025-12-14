#!/bin/bash
set -euo pipefail

# Bootstrap script for shifter dev AWS account
# Run with: AWS_PROFILE=panw-shifter-dev-workstation ./scripts/bootstrap-dev.sh

REGION="us-east-2"
GITHUB_ORG="Brad-Edwards"
GITHUB_REPO="shifter"

echo "=== Shifter Dev Account Bootstrap ==="
echo "Region: $REGION"
echo ""

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account ID: $ACCOUNT_ID"

# Generate UUID suffix
UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
echo "Generated UUID: $UUID"
echo ""

# --- S3 Bucket ---
BUCKET_NAME="shifter-dev-infra-${UUID}"
echo "Creating S3 bucket: $BUCKET_NAME"

aws s3api create-bucket \
    --bucket "$BUCKET_NAME" \
    --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"

aws s3api put-bucket-versioning \
    --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
    --bucket "$BUCKET_NAME" \
    --server-side-encryption-configuration '{
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
    }'

aws s3api put-public-access-block \
    --bucket "$BUCKET_NAME" \
    --public-access-block-configuration '{
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }'

echo "✓ S3 bucket created"

# --- DynamoDB Table ---
TABLE_NAME="shifter-dev-terraform-${UUID}"
echo "Creating DynamoDB table: $TABLE_NAME"

aws dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
echo "✓ DynamoDB table created"

# --- OIDC Provider ---
echo "Creating GitHub OIDC provider"

OIDC_ARN=$(aws iam create-open-id-connect-provider \
    --url "https://token.actions.githubusercontent.com" \
    --client-id-list "sts.amazonaws.com" \
    --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1" "1b511abead59c6ce207077c0bf0e0043b1382612" \
    --tags Key=Name,Value=github-actions-oidc-dev Key=Project,Value=shifter Key=Environment,Value=dev \
    --query OpenIDConnectProviderArn --output text 2>/dev/null || \
    aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" --output text)

echo "✓ OIDC provider: $OIDC_ARN"

# --- IAM Role ---
ROLE_NAME="github-actions-shifter-dev"
echo "Creating IAM role: $ROLE_NAME"

# Trust policy
cat > /tmp/trust-policy.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "${OIDC_ARN}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": "repo:${GITHUB_ORG}/${GITHUB_REPO}:*"
                }
            }
        }
    ]
}
EOF

aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document file:///tmp/trust-policy.json \
    --tags Key=Name,Value="$ROLE_NAME" Key=Project,Value=shifter Key=Environment,Value=dev

echo "✓ IAM role created"

# --- IAM Policies ---
echo "Creating IAM policies..."

# Core Infrastructure policy
cat > /tmp/core-infra.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECR",
            "Effect": "Allow",
            "Action": ["ecr:*"],
            "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/shifter-dev-*"
        },
        {
            "Sid": "ECRAuth",
            "Effect": "Allow",
            "Action": ["ecr:GetAuthorizationToken"],
            "Resource": "*"
        },
        {
            "Sid": "S3State",
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket",
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::shifter-dev-infra-*",
                "arn:aws:s3:::shifter-dev-infra-*/*"
            ]
        },
        {
            "Sid": "S3UserStorage",
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": "arn:aws:s3:::shifter-dev-user-storage-*"
        },
        {
            "Sid": "DynamoDB",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:DeleteItem"
            ],
            "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/shifter-dev-terraform-*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-core-infrastructure" \
    --policy-document file:///tmp/core-infra.json

# VPC Networking policy
cat > /tmp/vpc.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "VPC",
            "Effect": "Allow",
            "Action": [
                "ec2:*Vpc*",
                "ec2:*Subnet*",
                "ec2:*RouteTable*",
                "ec2:*Route",
                "ec2:*InternetGateway*",
                "ec2:*NatGateway*",
                "ec2:*Address*",
                "ec2:*SecurityGroup*",
                "ec2:*Tags",
                "ec2:Describe*",
                "ec2:CreateTags",
                "ec2:DeleteTags"
            ],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-vpc-networking" \
    --policy-document file:///tmp/vpc.json

# EC2 Instances policy
cat > /tmp/ec2.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "EC2",
            "Effect": "Allow",
            "Action": [
                "ec2:RunInstances",
                "ec2:TerminateInstances",
                "ec2:StartInstances",
                "ec2:StopInstances",
                "ec2:RebootInstances",
                "ec2:DescribeInstances",
                "ec2:DescribeInstanceStatus",
                "ec2:DescribeInstanceTypes",
                "ec2:DescribeInstanceAttribute",
                "ec2:ModifyInstanceAttribute",
                "ec2:DescribeImages",
                "ec2:DescribeVolumes",
                "ec2:CreateVolume",
                "ec2:DeleteVolume",
                "ec2:AttachVolume",
                "ec2:DetachVolume",
                "ec2:DescribeInstanceCreditSpecifications",
                "ec2:DescribeKeyPairs",
                "ec2:CreateKeyPair",
                "ec2:DeleteKeyPair"
            ],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-ec2-instances" \
    --policy-document file:///tmp/ec2.json

# ELB and ACM policy
cat > /tmp/elb-acm.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ELB",
            "Effect": "Allow",
            "Action": ["elasticloadbalancing:*"],
            "Resource": "*"
        },
        {
            "Sid": "ACM",
            "Effect": "Allow",
            "Action": ["acm:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-elb-acm" \
    --policy-document file:///tmp/elb-acm.json

# IAM Scoped policy
cat > /tmp/iam.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "IAMRoles",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:DeleteRole",
                "iam:GetRole",
                "iam:UpdateRole",
                "iam:TagRole",
                "iam:UntagRole",
                "iam:ListRolePolicies",
                "iam:ListAttachedRolePolicies",
                "iam:ListInstanceProfilesForRole",
                "iam:PutRolePolicy",
                "iam:GetRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:AttachRolePolicy",
                "iam:DetachRolePolicy"
            ],
            "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/*"
        },
        {
            "Sid": "IAMInstanceProfiles",
            "Effect": "Allow",
            "Action": [
                "iam:CreateInstanceProfile",
                "iam:DeleteInstanceProfile",
                "iam:GetInstanceProfile",
                "iam:AddRoleToInstanceProfile",
                "iam:RemoveRoleFromInstanceProfile",
                "iam:TagInstanceProfile",
                "iam:UntagInstanceProfile"
            ],
            "Resource": "arn:aws:iam::${ACCOUNT_ID}:instance-profile/*"
        },
        {
            "Sid": "IAMPassRole",
            "Effect": "Allow",
            "Action": ["iam:PassRole"],
            "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/*"
        },
        {
            "Sid": "IAMServiceLinkedRoles",
            "Effect": "Allow",
            "Action": ["iam:CreateServiceLinkedRole"],
            "Resource": "arn:aws:iam::*:role/aws-service-role/*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-iam-scoped" \
    --policy-document file:///tmp/iam.json

# Lambda and Step Functions policy
cat > /tmp/lambda-sfn.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "Lambda",
            "Effect": "Allow",
            "Action": [
                "lambda:CreateFunction",
                "lambda:DeleteFunction",
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:GetFunctionCodeSigningConfig",
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:ListVersionsByFunction",
                "lambda:PublishVersion",
                "lambda:AddPermission",
                "lambda:RemovePermission",
                "lambda:GetPolicy",
                "lambda:TagResource",
                "lambda:UntagResource",
                "lambda:ListTags"
            ],
            "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:*"
        },
        {
            "Sid": "LambdaLayers",
            "Effect": "Allow",
            "Action": [
                "lambda:PublishLayerVersion",
                "lambda:GetLayerVersion",
                "lambda:DeleteLayerVersion",
                "lambda:ListLayerVersions"
            ],
            "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:layer:*"
        },
        {
            "Sid": "StepFunctions",
            "Effect": "Allow",
            "Action": [
                "states:CreateStateMachine",
                "states:DeleteStateMachine",
                "states:DescribeStateMachine",
                "states:UpdateStateMachine",
                "states:ListStateMachines",
                "states:ListStateMachineVersions",
                "states:TagResource",
                "states:UntagResource",
                "states:ListTagsForResource"
            ],
            "Resource": "arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:*"
        },
        {
            "Sid": "StepFunctionsValidate",
            "Effect": "Allow",
            "Action": ["states:ValidateStateMachineDefinition"],
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:DeleteLogGroup",
                "logs:DescribeLogGroups",
                "logs:PutRetentionPolicy",
                "logs:TagLogGroup",
                "logs:UntagLogGroup",
                "logs:ListTagsLogGroup",
                "logs:ListTagsForResource",
                "logs:TagResource",
                "logs:UntagResource"
            ],
            "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:*"
        },
        {
            "Sid": "CloudWatchAlarms",
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:DeleteAlarms",
                "cloudwatch:DescribeAlarms",
                "cloudwatch:ListTagsForResource",
                "cloudwatch:TagResource",
                "cloudwatch:UntagResource"
            ],
            "Resource": "arn:aws:cloudwatch:${REGION}:${ACCOUNT_ID}:alarm:*"
        },
        {
            "Sid": "SNS",
            "Effect": "Allow",
            "Action": [
                "sns:CreateTopic",
                "sns:DeleteTopic",
                "sns:GetTopicAttributes",
                "sns:SetTopicAttributes",
                "sns:ListTagsForResource",
                "sns:TagResource",
                "sns:UntagResource",
                "sns:Subscribe",
                "sns:Unsubscribe",
                "sns:GetSubscriptionAttributes"
            ],
            "Resource": "arn:aws:sns:${REGION}:${ACCOUNT_ID}:*-dev-portal-*"
        },
        {
            "Sid": "EventBridge",
            "Effect": "Allow",
            "Action": [
                "events:PutRule",
                "events:DeleteRule",
                "events:DescribeRule",
                "events:EnableRule",
                "events:DisableRule",
                "events:PutTargets",
                "events:RemoveTargets",
                "events:ListTargetsByRule",
                "events:ListTagsForResource",
                "events:TagResource",
                "events:UntagResource"
            ],
            "Resource": "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/*-dev-portal-*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-lambda-sfn" \
    --policy-document file:///tmp/lambda-sfn.json

# RDS policy
cat > /tmp/rds.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RDS",
            "Effect": "Allow",
            "Action": [
                "rds:CreateDBInstance",
                "rds:DeleteDBInstance",
                "rds:DescribeDBInstances",
                "rds:ModifyDBInstance",
                "rds:RebootDBInstance",
                "rds:StartDBInstance",
                "rds:StopDBInstance",
                "rds:CreateDBSubnetGroup",
                "rds:DeleteDBSubnetGroup",
                "rds:DescribeDBSubnetGroups",
                "rds:ModifyDBSubnetGroup",
                "rds:CreateDBParameterGroup",
                "rds:DeleteDBParameterGroup",
                "rds:DescribeDBParameterGroups",
                "rds:ModifyDBParameterGroup",
                "rds:DescribeDBParameters",
                "rds:AddTagsToResource",
                "rds:RemoveTagsFromResource",
                "rds:ListTagsForResource",
                "rds:DescribeDBEngineVersions",
                "rds:DescribeOrderableDBInstanceOptions"
            ],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-rds" \
    --policy-document file:///tmp/rds.json

# Secrets Manager and KMS policy
cat > /tmp/secrets-kms.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SecretsManager",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:CreateSecret",
                "secretsmanager:DeleteSecret",
                "secretsmanager:DescribeSecret",
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue",
                "secretsmanager:UpdateSecret",
                "secretsmanager:TagResource",
                "secretsmanager:UntagResource",
                "secretsmanager:GetResourcePolicy",
                "secretsmanager:PutResourcePolicy",
                "secretsmanager:DeleteResourcePolicy"
            ],
            "Resource": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:shifter-dev-*"
        },
        {
            "Sid": "SecretsManagerRandom",
            "Effect": "Allow",
            "Action": ["secretsmanager:GetRandomPassword"],
            "Resource": "*"
        },
        {
            "Sid": "KMS",
            "Effect": "Allow",
            "Action": [
                "kms:CreateKey",
                "kms:DescribeKey",
                "kms:CreateAlias",
                "kms:DeleteAlias",
                "kms:ListAliases",
                "kms:Encrypt",
                "kms:Decrypt",
                "kms:GenerateDataKey",
                "kms:TagResource",
                "kms:UntagResource",
                "kms:ScheduleKeyDeletion"
            ],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-secrets-kms" \
    --policy-document file:///tmp/secrets-kms.json

# SSM and Cognito policy
cat > /tmp/ssm-cognito.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SSM",
            "Effect": "Allow",
            "Action": [
                "ssm:SendCommand",
                "ssm:GetCommandInvocation",
                "ssm:ListCommandInvocations",
                "ssm:DescribeInstanceInformation"
            ],
            "Resource": "*"
        },
        {
            "Sid": "Cognito",
            "Effect": "Allow",
            "Action": ["cognito-idp:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-dev-ssm-cognito" \
    --policy-document file:///tmp/ssm-cognito.json

echo "✓ All IAM policies attached"

# Cleanup temp files
rm -f /tmp/trust-policy.json /tmp/core-infra.json /tmp/vpc.json /tmp/ec2.json \
      /tmp/elb-acm.json /tmp/iam.json /tmp/lambda-sfn.json /tmp/rds.json \
      /tmp/secrets-kms.json /tmp/ssm-cognito.json

# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)

echo ""
echo "=== Bootstrap Complete ==="
echo ""
echo "Add these to GitHub secrets:"
echo "  AWS_ROLE_ARN_DEV: $ROLE_ARN"
echo ""
echo "Use these in terraform/environments/dev/backend.tf:"
echo ""
cat <<EOF
terraform {
  backend "s3" {
    bucket         = "${BUCKET_NAME}"
    key            = "shifter/dev/terraform.tfstate"
    region         = "${REGION}"
    dynamodb_table = "${TABLE_NAME}"
    encrypt        = true
  }

  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = "dev"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }
  }
}
EOF
