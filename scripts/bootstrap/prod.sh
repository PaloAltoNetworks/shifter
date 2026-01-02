#!/bin/bash
set -euo pipefail

# Bootstrap script for shifter prod AWS account
# Run with: AWS_PROFILE=<your-prod-profile> ./scripts/bootstrap/prod.sh
#
# This script creates:
# - S3 bucket for Terraform state
# - DynamoDB table for Terraform locking
# - GitHub OIDC provider for keyless CI/CD auth
# - IAM role with permissions for all Shifter infrastructure

REGION="us-east-2"
GITHUB_ORG="Brad-Edwards"
GITHUB_REPO="shifter"

echo "=== Shifter Prod Account Bootstrap ==="
echo "Region: $REGION"
echo ""

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account ID: $ACCOUNT_ID"

# Generate UUID suffix for uniqueness
UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
echo "Generated UUID: $UUID"
echo ""

# --- S3 Bucket for Terraform State ---
BUCKET_NAME="shifter-infra-${UUID}"
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

# --- DynamoDB Table for Terraform Locking ---
TABLE_NAME="shifter-terraform-${UUID}"
echo "Creating DynamoDB table: $TABLE_NAME"

aws dynamodb create-table \
    --table-name "$TABLE_NAME" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
echo "✓ DynamoDB table created"

# --- GitHub OIDC Provider ---
echo "Creating GitHub OIDC provider"

OIDC_ARN=$(aws iam create-open-id-connect-provider \
    --url "https://token.actions.githubusercontent.com" \
    --client-id-list "sts.amazonaws.com" \
    --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1" "1b511abead59c6ce207077c0bf0e0043b1382612" \
    --tags Key=Name,Value=github-actions-oidc Key=Project,Value=shifter Key=Environment,Value=prod \
    --query OpenIDConnectProviderArn --output text 2>/dev/null || \
    aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" --output text)

echo "✓ OIDC provider: $OIDC_ARN"

# --- IAM Role ---
ROLE_NAME="github-actions-shifter-prod"
echo "Creating IAM role: $ROLE_NAME"

# Trust policy - allows GitHub Actions to assume this role
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
    --tags Key=Name,Value="$ROLE_NAME" Key=Project,Value=shifter Key=Environment,Value=prod

echo "✓ IAM role created"

# --- IAM Policies ---
echo "Creating IAM policies..."

# 1. Core Infrastructure (ECR, S3, DynamoDB)
cat > /tmp/core-infra.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECR",
            "Effect": "Allow",
            "Action": ["ecr:*"],
            "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/shifter-*"
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
                "arn:aws:s3:::shifter-infra-*",
                "arn:aws:s3:::shifter-infra-*/*"
            ]
        },
        {
            "Sid": "S3Buckets",
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": [
                "arn:aws:s3:::shifter-*",
                "arn:aws:s3:::shifter-*/*"
            ]
        },
        {
            "Sid": "DynamoDB",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:DeleteItem",
                "dynamodb:CreateTable",
                "dynamodb:DeleteTable",
                "dynamodb:DescribeTable",
                "dynamodb:UpdateTable",
                "dynamodb:TagResource",
                "dynamodb:UntagResource",
                "dynamodb:ListTagsOfResource"
            ],
            "Resource": [
                "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/shifter-*"
            ]
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-core-infrastructure" \
    --policy-document file:///tmp/core-infra.json

# 2. VPC Networking
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
                "ec2:*FlowLog*",
                "ec2:*VpcEndpoint*",
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
    --policy-name "shifter-prod-vpc-networking" \
    --policy-document file:///tmp/vpc.json

# 3. EC2 Instances
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
                "ec2:DeleteKeyPair",
                "ec2:*LaunchTemplate*"
            ],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-ec2-instances" \
    --policy-document file:///tmp/ec2.json

# 4. ELB, ACM, WAF
cat > /tmp/elb-acm-waf.json <<EOF
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
        },
        {
            "Sid": "WAF",
            "Effect": "Allow",
            "Action": ["wafv2:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-elb-acm-waf" \
    --policy-document file:///tmp/elb-acm-waf.json

# 5. IAM (scoped)
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
    --policy-name "shifter-prod-iam-scoped" \
    --policy-document file:///tmp/iam.json

# 6. Lambda, Step Functions, CloudWatch, SNS, EventBridge
cat > /tmp/lambda-sfn.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "Lambda",
            "Effect": "Allow",
            "Action": ["lambda:*"],
            "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:*"
        },
        {
            "Sid": "LambdaLayers",
            "Effect": "Allow",
            "Action": ["lambda:*"],
            "Resource": "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:layer:*"
        },
        {
            "Sid": "StepFunctions",
            "Effect": "Allow",
            "Action": ["states:*"],
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
            "Action": ["logs:*"],
            "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:*"
        },
        {
            "Sid": "CloudWatchAlarms",
            "Effect": "Allow",
            "Action": ["cloudwatch:*"],
            "Resource": "*"
        },
        {
            "Sid": "SNS",
            "Effect": "Allow",
            "Action": ["sns:*"],
            "Resource": "arn:aws:sns:${REGION}:${ACCOUNT_ID}:*"
        },
        {
            "Sid": "EventBridge",
            "Effect": "Allow",
            "Action": ["events:*"],
            "Resource": "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-lambda-sfn" \
    --policy-document file:///tmp/lambda-sfn.json

# 7. RDS
cat > /tmp/rds.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RDS",
            "Effect": "Allow",
            "Action": ["rds:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-rds" \
    --policy-document file:///tmp/rds.json

# 8. Secrets Manager and KMS
cat > /tmp/secrets-kms.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SecretsManager",
            "Effect": "Allow",
            "Action": ["secretsmanager:*"],
            "Resource": "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:shifter-*"
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
            "Action": ["kms:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-secrets-kms" \
    --policy-document file:///tmp/secrets-kms.json

# 9. SSM and Cognito
cat > /tmp/ssm-cognito.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SSM",
            "Effect": "Allow",
            "Action": ["ssm:*"],
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
    --policy-name "shifter-prod-ssm-cognito" \
    --policy-document file:///tmp/ssm-cognito.json

# 10. ECS (for Pulumi Provisioner)
cat > /tmp/ecs.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ECS",
            "Effect": "Allow",
            "Action": ["ecs:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-ecs" \
    --policy-document file:///tmp/ecs.json

# 11. ElastiCache (Redis)
cat > /tmp/elasticache.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ElastiCache",
            "Effect": "Allow",
            "Action": ["elasticache:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-elasticache" \
    --policy-document file:///tmp/elasticache.json

# 12. Network Firewall (Range VPC)
cat > /tmp/networkfirewall.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "NetworkFirewall",
            "Effect": "Allow",
            "Action": ["network-firewall:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-networkfirewall" \
    --policy-document file:///tmp/networkfirewall.json

# 13. Kinesis Firehose and SQS (Log Aggregation)
cat > /tmp/firehose-sqs.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "Firehose",
            "Effect": "Allow",
            "Action": ["firehose:*"],
            "Resource": "*"
        },
        {
            "Sid": "SQS",
            "Effect": "Allow",
            "Action": ["sqs:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-firehose-sqs" \
    --policy-document file:///tmp/firehose-sqs.json

# 14. Auto Scaling (ASG for dev portal)
cat > /tmp/autoscaling.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AutoScaling",
            "Effect": "Allow",
            "Action": ["autoscaling:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-autoscaling" \
    --policy-document file:///tmp/autoscaling.json

# 15. Budgets (cost alerts)
cat > /tmp/budgets.json <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "Budgets",
            "Effect": "Allow",
            "Action": ["budgets:*"],
            "Resource": "*"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "shifter-prod-budgets" \
    --policy-document file:///tmp/budgets.json

echo "✓ All IAM policies attached"

# Cleanup temp files
rm -f /tmp/trust-policy.json /tmp/core-infra.json /tmp/vpc.json /tmp/ec2.json \
      /tmp/elb-acm-waf.json /tmp/iam.json /tmp/lambda-sfn.json /tmp/rds.json \
      /tmp/secrets-kms.json /tmp/ssm-cognito.json /tmp/ecs.json /tmp/elasticache.json \
      /tmp/networkfirewall.json /tmp/firehose-sqs.json /tmp/autoscaling.json /tmp/budgets.json

# Get role ARN
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)

echo ""
echo "=== Bootstrap Complete ==="
echo ""
echo "STEP 1: Add to GitHub Secrets (Settings → Secrets → Actions):"
echo "  AWS_ROLE_ARN: $ROLE_ARN"
echo ""
echo "STEP 2: Update backend.tf files with these values:"
echo ""
echo "--- platform/terraform/environments/prod/backend.tf ---"
cat <<EOF
terraform {
  backend "s3" {
    bucket         = "${BUCKET_NAME}"
    key            = "shifter/prod/terraform.tfstate"
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
      Environment = "prod"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }
  }
}
EOF

echo ""
echo "--- platform/terraform/environments/prod/portal/backend.tf ---"
cat <<EOF
terraform {
  backend "s3" {
    bucket         = "${BUCKET_NAME}"
    key            = "shifter/prod/portal/terraform.tfstate"
    region         = "${REGION}"
    dynamodb_table = "${TABLE_NAME}"
    encrypt        = true
  }
}
EOF

echo ""
echo "--- platform/terraform/environments/prod/range/backend.tf ---"
cat <<EOF
terraform {
  backend "s3" {
    bucket         = "${BUCKET_NAME}"
    key            = "shifter/prod/range/terraform.tfstate"
    region         = "${REGION}"
    dynamodb_table = "${TABLE_NAME}"
    encrypt        = true
  }
}
EOF

echo ""
echo "STEP 3: Deploy in order:"
echo "  1. platform/terraform/environments/prod/        (Core: ECR repos)"
echo "  2. platform/terraform/environments/prod/range/  (Range VPC + Pulumi state)"
echo "  3. platform/terraform/environments/prod/portal/ (Portal infrastructure)"
echo ""
echo "STEP 4: After Portal deploy, wait for ACM certificate validation:"
echo "  - Watch terraform output for CNAME records"
echo "  - Add CNAME records to your DNS provider"
echo "  - Wait ~5 min for validation"
echo ""
echo "STEP 5: Point your domain to the ALB DNS name from terraform output"
echo ""
