#!/bin/bash
set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Error: Version argument required"
  echo "Usage: $0 <version>"
  echo "Example: $0 0.2.0"
  exit 1
fi

VERSION=$1

if [ -z "$VERSION" ]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 0.2.0"
  exit 1
fi

# Validate version format (basic semantic versioning)
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: Version must be in format X.Y.Z (e.g., 0.2.0)"
  exit 1
fi

echo "Bumping version to $VERSION..."

# Update sonar-project.properties
SONAR_PROPS="sonar-project.properties"
if [ -f "$SONAR_PROPS" ]; then
  sed -i "s/sonar.projectVersion=.*/sonar.projectVersion=$VERSION/" "$SONAR_PROPS"
  echo "Updated $SONAR_PROPS"
else
  echo "Error: $SONAR_PROPS not found"
  exit 1
fi

echo "Version bumped to $VERSION successfully!"
