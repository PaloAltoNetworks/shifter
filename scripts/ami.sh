#!/bin/bash
# AMI build and promote script
# Usage:
#   ./scripts/ami.sh -b kali    # Build AMI in dev
#   ./scripts/ami.sh -p kali    # Promote AMI to prod

set -e

REPO="Brad-Edwards/shifter"
BRANCH=$(git rev-parse --abbrev-ref HEAD)

usage() {
    echo "Usage: $0 [-b|-p] <ami_type>"
    echo ""
    echo "Options:"
    echo "  -b <type>   Build AMI in dev (runs packer.yml)"
    echo "  -p <type>   Promote AMI to prod (runs packer-promote.yml)"
    echo ""
    echo "AMI types: kali"
    echo ""
    echo "Current branch: $BRANCH"
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
        echo "Branch: $BRANCH"
        gh workflow run packer.yml \
            --repo "$REPO" \
            --ref "$BRANCH" \
            -f ami_type="$AMI_TYPE"
        echo "Workflow triggered. View at: https://github.com/$REPO/actions/workflows/packer.yml"
        ;;
    -p)
        echo "Promoting $AMI_TYPE AMI to prod..."
        echo "Branch: $BRANCH"
        gh workflow run packer-promote.yml \
            --repo "$REPO" \
            --ref "$BRANCH" \
            -f ami_type="$AMI_TYPE"
        echo "Workflow triggered. View at: https://github.com/$REPO/actions/workflows/packer-promote.yml"
        ;;
    *)
        usage
        ;;
esac
