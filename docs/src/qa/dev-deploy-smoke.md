# Dev Environment First Deploy Checklist

Complete smoke test for a fresh dev environment deployment.

## Prerequisites

- Dev AWS account bootstrapped (`scripts/bootstrap-dev.sh`)
- GitHub secrets configured (`AWS_ROLE_ARN_DEV`, `TF_VARS_DEV_*`)
- `dev` branch created
- DNS access for ACM validation

## Environment Setup

```bash
export ENV=dev
export AWS_PROFILE=panw-shifter-dev-workstation
export AWS_REGION=us-east-2
export DOMAIN=dev.shifter.keplerops.com
```

## Phase 1: Infrastructure Deploy

### 1.1 Core (ECR)

```bash
cd terraform/environments/dev
terraform init
terraform apply
```

Verify:
```bash
aws ecr describe-repositories --repository-names shifter-dev-portal \
  && echo "PASS: ECR repo exists" || echo "FAIL: ECR repo not found"
```

### 1.2 Range VPC

```bash
cd terraform/environments/dev/range
terraform init
terraform apply
```

Run: [Range Smoke Test](range-smoke.md)

### 1.3 Portal

```bash
cd terraform/environments/dev/portal
terraform init
terraform apply  # Will pause for ACM validation
```

**ACM Validation:**
1. Watch terraform output for CNAME records
2. Create DNS records in your DNS provider
3. Wait for validation (5-10 min)
4. Terraform continues automatically

**DNS Setup:**
1. Get ALB DNS name: `terraform output alb_dns_name`
2. Create CNAME: `dev.shifter.keplerops.com` → ALB DNS name

Verify:
```bash
curl -sf "https://${DOMAIN}/health/" && echo "PASS: Portal accessible" || echo "FAIL: Portal not accessible"
```

### 1.4 LibreChat

```bash
cd terraform/environments/dev/librechat
terraform init
terraform apply
```

Run: [LibreChat Smoke Test](librechat-smoke.md)

## Phase 2: Application Deploy

### 2.1 Build and Push Portal Image

```bash
cd portal
docker build -t shifter-dev-portal .

# Get ECR login
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-2.amazonaws.com

# Tag and push
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
docker tag shifter-dev-portal:latest ${ACCOUNT}.dkr.ecr.us-east-2.amazonaws.com/shifter-dev-portal:latest
docker push ${ACCOUNT}.dkr.ecr.us-east-2.amazonaws.com/shifter-dev-portal:latest
```

### 2.2 Deploy Portal Container

Via SSM or wait for GitHub Actions on push to `dev` branch.

### 2.3 Deploy LibreChat

LibreChat deploys automatically via terraform user_data. To redeploy:

```bash
# Trigger via GitHub Actions workflow_dispatch
# Or manually via SSM
```

## Phase 3: Functional Tests

### 3.1 Portal Smoke

Run automated checks from [Portal Smoke Test](portal-smoke.md), then manually:

- [ ] Health check: `curl https://dev.shifter.keplerops.com/health/`
- [ ] Open portal in browser
- [ ] Cognito redirect works
- [ ] Login with test user
- [ ] Dashboard loads, shows your ranges

### 3.2 Provisioner Smoke

Run automated checks from [Provisioner Smoke Test](provisioner-smoke.md), then manually:

- [ ] State machines exist (check Step Functions console)
- [ ] Lambda functions exist (check Lambda console)
- [ ] Launch a range from Portal UI
- [ ] Verify victim EC2 created (check EC2 console, filter by range_id tag)
- [ ] Verify Kali EC2 created
- [ ] Teardown range from Portal UI
- [ ] Verify resources cleaned up (EC2s terminated, subnet deleted)

### 3.3 LibreChat Smoke

Run automated checks from [LibreChat Smoke Test](librechat-smoke.md), then manually:

- [ ] EC2 running (check AWS console or CLI)
- [ ] Docker containers healthy (via SSM)
- [ ] Open LibreChat in browser
- [ ] Register/login works
- [ ] Send a chat message, Bedrock responds

## Phase 4: End-to-End Test (Manual)

Complete user journey in browser:

1. [ ] Open `https://dev.shifter.keplerops.com/`
2. [ ] Login via Cognito (use test account)
3. [ ] Upload a test agent binary (any small file)
4. [ ] Click "Launch Range"
5. [ ] Wait for status to show "ready" (2-3 min)
6. [ ] Click the LibreChat link from the range card
7. [ ] Login to LibreChat, start a chat
8. [ ] Send a message, verify Bedrock responds
9. [ ] Return to Portal, click "Teardown Range"
10. [ ] Verify status changes to "terminated"
11. [ ] Confirm in AWS console: EC2s terminated, subnet deleted

## Summary Checklist

| Component | Status |
|-----------|--------|
| ECR Repository | [ ] |
| Range VPC | [ ] |
| Portal Infrastructure | [ ] |
| ACM Certificate | [ ] |
| DNS Configuration | [ ] |
| Portal Application | [ ] |
| LibreChat Infrastructure | [ ] |
| LibreChat Application | [ ] |
| Provisioner State Machines | [ ] |
| Provisioner Lambdas | [ ] |
| End-to-End Range Lifecycle | [ ] |

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| ACM validation stuck | Check DNS records, wait up to 30 min |
| Portal 502 | Check EC2 is running, container started |
| Cognito redirect loop | Check callback URLs in Cognito app client |
| Provisioner timeout | Check Lambda logs in CloudWatch |
| LibreChat no response | Check Bedrock IAM permissions |

## Cleanup (Optional)

To destroy dev environment:

```bash
# Reverse order
cd terraform/environments/dev/librechat && terraform destroy
cd terraform/environments/dev/portal && terraform destroy
cd terraform/environments/dev/range && terraform destroy
cd terraform/environments/dev && terraform destroy
```

