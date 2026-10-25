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
    echo "  Base: kali, ubuntu, windows, dc, brokenbk"
    echo "Dispatch ref: $WORKFLOW_REF (current branch: $BRANCH; override with AMI_WORKFLOW_REF=main)"
    exit 1
}

if [[ $# -lt 2 ]]; then
    usage
fi

ACTION=$1
AMI_TYPE=$2

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
