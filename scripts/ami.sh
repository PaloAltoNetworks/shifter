#!/bin/bash
# AMI build and promote script
# Usage:
#   ./scripts/ami.sh -b kali    # Build AMI in dev
#   ./scripts/ami.sh -p kali    # Promote AMI to prod

set -e

REPO="Brad-Edwards/shifter"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Base/DC builds and prod promotions run only from a protected ref: a
# feature-branch copy of the workflow could otherwise weaken its own inline
# protected-ref gate before it runs (#1656). Dispatch against dev by default;
# override to main with AMI_WORKFLOW_REF=main. Non-protected refs are refused
# here so this helper never advertises a bypass the workflow/IAM will reject.
WORKFLOW_REF="${AMI_WORKFLOW_REF:-dev}"
case "$WORKFLOW_REF" in
    dev | main) ;;
    *)
        echo "Error: AMI_WORKFLOW_REF must be 'dev' or 'main' (got '$WORKFLOW_REF')" >&2
        exit 1
        ;;
esac

usage() {
    echo "Usage: $0 [-b|-p] <ami_type>"
    echo ""
    echo "Options:"
    echo "  -b <type>   Build AMI in dev (runs packer.yml)"
    echo "  -p <type>   Promote AMI to prod (runs packer-promote.yml)"
    echo ""
    echo "AMI types:"
    echo "  Base: kali, ubuntu, windows, dc, polaris-dc, brokenbk"
    echo "  Scenario: techvault, polaris-vm (need extra inputs; see note below)"
    echo ""
    echo "Scenario bakes run over the no-inbound SSM communicator and require an"
    echo "operator-supplied isolated bake subnet/security-group/instance-profile"
    echo "(and, for polaris-vm, the S3 build tarball). Dispatch them with the extra"
    echo "-f inputs, e.g.:"
    echo "  gh workflow run packer.yml --repo $REPO --ref $WORKFLOW_REF \\"
    echo "    -f ami_type=techvault -f subnet_id=subnet-... -f security_group_id=sg-... \\"
    echo "    -f instance_profile=<ssm-profile> [-f aptl_version=4.1.2]"
    echo ""
    echo "Dispatch ref: $WORKFLOW_REF (current branch: $BRANCH; override with AMI_WORKFLOW_REF=main)"
    exit 1
}

# Scenario AMIs need extra dispatch inputs this helper does not collect; refuse a
# doomed one-arg dispatch and point at the full command instead.
is_scenario_type() {
    case "$1" in
        techvault | polaris-vm) return 0 ;;
        *) return 1 ;;
    esac
}

if [[ $# -lt 2 ]]; then
    usage
fi

ACTION=$1
AMI_TYPE=$2

if is_scenario_type "$AMI_TYPE"; then
    echo "'$AMI_TYPE' is a scenario AMI and needs extra dispatch inputs this helper does not collect."
    echo "Dispatch it directly, e.g.:"
    echo "  gh workflow run packer.yml --repo $REPO --ref $WORKFLOW_REF \\"
    echo "    -f ami_type=$AMI_TYPE -f subnet_id=subnet-... -f security_group_id=sg-... \\"
    echo "    -f instance_profile=<ssm-profile>$([ "$AMI_TYPE" = polaris-vm ] && echo ' -f s3_tarball_uri=s3://bucket/key' || echo ' [-f aptl_version=4.1.2]')"
    exit 1
fi

case $ACTION in
    -b)
        echo "Building $AMI_TYPE AMI in dev..."
        echo "Ref: $WORKFLOW_REF"
        gh workflow run packer.yml \
            --repo "$REPO" \
            --ref "$WORKFLOW_REF" \
            -f ami_type="$AMI_TYPE"
        echo "Workflow triggered. View at: https://github.com/$REPO/actions/workflows/packer.yml"
        ;;
    -p)
        echo "Promoting $AMI_TYPE AMI to prod..."
        echo "Ref: $WORKFLOW_REF"
        gh workflow run packer-promote.yml \
            --repo "$REPO" \
            --ref "$WORKFLOW_REF" \
            -f ami_type="$AMI_TYPE"
        echo "Workflow triggered. View at: https://github.com/$REPO/actions/workflows/packer-promote.yml"
        ;;
    *)
        usage
        ;;
esac
