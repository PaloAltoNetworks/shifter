#!/bin/bash
# Build a VM image with Packer and push it to Artifact Registry as a containerDisk.
#
# Usage:
#   ./build-and-push.sh <image_type> <artifact_registry_path>
#
# Examples:
#   ./build-and-push.sh ubuntu us-central1-docker.pkg.dev/my-project/dev-range-vm-images
#   ./build-and-push.sh kali us-central1-docker.pkg.dev/my-project/dev-range-vm-images
#   ./build-and-push.sh windows us-central1-docker.pkg.dev/my-project/dev-range-vm-images
#   ./build-and-push.sh dc us-central1-docker.pkg.dev/my-project/dev-range-vm-images
#
# Requires: packer, docker (or podman), gcloud (authenticated)
set -euo pipefail

IMAGE_TYPE="${1:?Usage: $0 <image_type> <artifact_registry_path>}"
REGISTRY="${2:?Usage: $0 <image_type> <artifact_registry_path>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

echo "=== Building ${IMAGE_TYPE} with Packer (QEMU) ==="
packer init .
packer build -only="qemu.${IMAGE_TYPE}" .

# Find the output qcow2
DISK_IMAGE="output/${IMAGE_TYPE}/"*.qcow2
if [ ! -f $DISK_IMAGE ]; then
    echo "ERROR: No qcow2 found in output/${IMAGE_TYPE}/"
    exit 1
fi
echo "Built disk image: ${DISK_IMAGE}"

echo "=== Wrapping in containerDisk ==="
TAG="${REGISTRY}/${IMAGE_TYPE}:$(date +%Y%m%d%H%M%S)"
TAG_LATEST="${REGISTRY}/${IMAGE_TYPE}:latest"

docker build \
    --build-arg "DISK_IMAGE=${DISK_IMAGE}" \
    -f Dockerfile.containerDisk \
    -t "${TAG}" \
    -t "${TAG_LATEST}" \
    .

echo "=== Pushing to Artifact Registry ==="
# Configure Docker for Artifact Registry (extracts region from registry path)
AR_HOST="${REGISTRY%%/*}"
gcloud auth configure-docker "${AR_HOST}" --quiet

docker push "${TAG}"
docker push "${TAG_LATEST}"

echo "=== Done ==="
echo "Image: ${TAG}"
echo "Latest: ${TAG_LATEST}"
echo ""
echo "Use in KubeVirt VirtualMachine:"
echo "  containerDisk:"
echo "    image: ${TAG_LATEST}"
