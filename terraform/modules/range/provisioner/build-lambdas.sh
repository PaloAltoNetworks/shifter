#!/bin/bash
# Build Lambda packages with shared code included
# Run this BEFORE terraform plan/apply

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/lambda"
BUILD_DIR="${SCRIPT_DIR}/build"

# Lambda functions to package
LAMBDAS=(
    "create_subnet"
    "create_victim"
    "create_kali"
    "configure_librechat"
    "cleanup"
    "find_stale_ranges"
)

echo "Building Lambda packages..."
echo "Source: ${LAMBDA_DIR}"
echo "Output: ${BUILD_DIR}"

# Clean and create build directory
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

for lambda in "${LAMBDAS[@]}"; do
    echo "  Packaging ${lambda}..."
    pkg_dir="${BUILD_DIR}/${lambda}_pkg"
    mkdir -p "${pkg_dir}"

    # Copy lambda code
    cp -r "${LAMBDA_DIR}/${lambda}"/* "${pkg_dir}/"

    # Copy shared module
    cp -r "${LAMBDA_DIR}/shared" "${pkg_dir}/"
done

echo "Done. Lambda packages ready in ${BUILD_DIR}/"
