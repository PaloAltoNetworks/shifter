#!/usr/bin/env bash
# Post-deploy live range smoke (issue #218).
#
# Runs ``python manage.py run_post_deploy_smoke`` inside the deployed portal pod
# on EKS via ``kubectl exec``. The AWS portal runtime is EKS (the portal runs as
# the ``portal-web`` Deployment in the platform namespace), so the smoke execs
# into a live portal pod rather than SSM-ing into an ASG/EC2 instance. Requires
# AWS credentials with EKS access, kubectl, and the env vars documented in
# scripts/post_deploy_smoke/README.md.
set -euo pipefail

VARIANT="linux"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant)
      VARIANT="${2:?--variant requires a value}"
      shift 2
      ;;
    -h | --help)
      echo "Usage: $0 [--variant linux|windows]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

ENVIRONMENT="${ENV:-dev}"
AWS_REGION="${AWS_REGION:-us-east-2}"
CLUSTER_NAME="${SHIFTER_EKS_CLUSTER_NAME:-shifter-${ENVIRONMENT}-eks}"
NAMESPACE="${SHIFTER_PLATFORM_NAMESPACE:-shifter-platform}"
PORTAL_DEPLOYMENT="${SHIFTER_PORTAL_DEPLOYMENT:-deploy/portal-web}"

if [[ -z "${SMOKE_TEST_USER_EMAIL:-}" ]]; then
  echo "::error::SMOKE_TEST_USER_EMAIL is required" >&2
  exit 1
fi

# Point kubectl at the private EKS API. The endpoint is private-only and its
# Route 53 zone is service-owned (cannot associate the runner VPC), so the runner
# cannot resolve the endpoint hostname. Connect by the control-plane ENI IP,
# reached over the runner<->EKS peering, with tls-server-name set to the endpoint
# host so the presented server certificate still validates. The runner's deploy
# role holds cluster-admin access, so `aws eks get-token` authenticates directly.
ENDPOINT="$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.endpoint' --output text)"
ENDPOINT_HOST="${ENDPOINT#https://}"
ENDPOINT_HOST="${ENDPOINT_HOST%%/*}"
CA_DATA="$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${AWS_REGION}" --query 'cluster.certificateAuthority.data' --output text)"
API_IP="$(aws ec2 describe-network-interfaces --region "${AWS_REGION}" \
  --filters "Name=description,Values=Amazon EKS ${CLUSTER_NAME}" "Name=status,Values=in-use" \
  --query 'NetworkInterfaces[0].PrivateIpAddress' --output text)"
if [[ -z "${API_IP}" || "${API_IP}" == "None" ]]; then
  echo "::error::No in-use EKS control-plane ENI found for ${CLUSTER_NAME}" >&2
  exit 1
fi
KUBECONFIG="$(mktemp)"
export KUBECONFIG
cat > "${KUBECONFIG}" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: ${CLUSTER_NAME}
    cluster:
      server: https://${API_IP}:443
      tls-server-name: ${ENDPOINT_HOST}
      certificate-authority-data: ${CA_DATA}
contexts:
  - name: ${CLUSTER_NAME}
    context: {cluster: ${CLUSTER_NAME}, user: ${CLUSTER_NAME}}
current-context: ${CLUSTER_NAME}
users:
  - name: ${CLUSTER_NAME}
    user:
      exec:
        apiVersion: client.authentication.k8s.io/v1beta1
        command: aws
        args: [--region, ${AWS_REGION}, eks, get-token, --cluster-name, ${CLUSTER_NAME}, --output, json]
EOF

# The manage command runs inside the portal pod via `kubectl exec`, which starts
# a fresh process that inherits neither this job's environment nor the runtime
# secrets the portal entrypoint hydrates in-process (DJANGO_SECRET_KEY,
# FIELD_ENCRYPTION_KEY, DB credentials — never baked into the container env). So
# run through `entrypoint.sh`, which fetches those secrets from Secrets Manager
# and switches on RDS IAM auth before exec-ing the command, with SKIP_MIGRATIONS
# set (the deploy already migrated; the smoke only provisions/tears down a range).
# Forward the smoke user identity explicitly with `env`. The smoke provisions
# ranges from base AMIs (no XDR agent), so there are no per-variant agent IDs.
kubectl exec -n "${NAMESPACE}" "${PORTAL_DEPLOYMENT}" -- \
  env "SMOKE_TEST_USER_EMAIL=${SMOKE_TEST_USER_EMAIL}" SKIP_MIGRATIONS=1 \
  /app/entrypoint.sh python manage.py run_post_deploy_smoke --variant "${VARIANT}"
