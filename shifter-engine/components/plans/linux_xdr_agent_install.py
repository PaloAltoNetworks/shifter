"""Linux XDR Agent installation plan.

Defines the steps to download and install Cortex XDR agent on Linux
victim instances via SSM Run Command.

Supports multiple installer formats:
- .sh (shell script)
- .deb (Debian/Ubuntu)
- .rpm (RHEL/Amazon Linux)
- .tar.gz / .zip (archived installers)

Based on logic from victim_linux.sh.j2 template.
"""

from typing import Any, Dict, List

from ..setup_plan import SetupStep


# Bash script to download XDR agent from presigned URL
DOWNLOAD_XDR_SCRIPT = '''#!/bin/bash
set -euo pipefail

presigned_url="{{ agent_presigned_url }}"
installer_path="/tmp/agent-installer"

echo "Downloading XDR agent installer..."

# Download using curl with proper options for S3 presigned URLs
curl -sSf -o "$installer_path" "$presigned_url"

if [ -f "$installer_path" ]; then
    file_size=$(stat -c%s "$installer_path" 2>/dev/null || stat -f%z "$installer_path")
    echo "Download complete: $installer_path ($file_size bytes)"
else
    echo "ERROR: Failed to download installer"
    exit 1
fi

exit 0
'''

# Bash script to install XDR agent
# Handles multiple installer formats: .sh, .deb, .rpm, .tar.gz, .zip
INSTALL_XDR_SCRIPT = '''#!/bin/bash
set -euo pipefail

installer_path="/tmp/agent-installer"
extract_dir="/tmp/agent-extract"

echo "Installing XDR agent..."

# Helper to deploy cortex.conf before running installer
deploy_cortex_conf() {
    local search_dir="$1"
    local conf_file=""

    # Find cortex.conf in directory
    conf_file=$(find "$search_dir" -name "cortex.conf" -type f 2>/dev/null | head -1)

    if [ -n "$conf_file" ]; then
        echo "Found cortex.conf: $conf_file"
        mkdir -p /etc/panw
        cp "$conf_file" /etc/panw/cortex.conf
        chmod 644 /etc/panw/cortex.conf
        echo "Deployed cortex.conf to /etc/panw/"
        return 0
    fi

    echo "WARNING: No cortex.conf found in archive"
    return 1
}

# Helper to find and run installer in extracted directory
run_extracted_installer() {
    local search_dir="$1"
    local installer=""

    # IMPORTANT: Deploy cortex.conf BEFORE running installer
    deploy_cortex_conf "$search_dir" || true

    # Try .sh first (check root first, then subdirs)
    installer=$(find "$search_dir" -maxdepth 1 -name "*.sh" -type f 2>/dev/null | head -1)
    if [ -z "$installer" ]; then
        installer=$(find "$search_dir" -maxdepth 2 -name "*.sh" -type f 2>/dev/null | head -1)
    fi
    if [ -n "$installer" ]; then
        echo "Found installer script: $installer"
        chmod +x "$installer"
        "$installer"
        return 0
    fi

    # Try .deb
    installer=$(find "$search_dir" -maxdepth 2 -name "*.deb" -type f 2>/dev/null | head -1)
    if [ -n "$installer" ]; then
        echo "Found .deb package: $installer"
        dpkg -i "$installer" || apt-get install -f -y
        return 0
    fi

    # Try .rpm
    installer=$(find "$search_dir" -maxdepth 2 -name "*.rpm" -type f 2>/dev/null | head -1)
    if [ -n "$installer" ]; then
        echo "Found .rpm package: $installer"
        rpm -i "$installer" || yum install -y "$installer" || dnf install -y "$installer"
        return 0
    fi

    echo "ERROR: No installer found in archive (.sh, .deb, or .rpm)"
    find "$search_dir" -type f
    return 1
}

# Detect file type and install
install_agent() {
    local file="$1"

    # Detect by MIME type
    local mime_type=$(file -b --mime-type "$file")
    echo "Detected MIME type: $mime_type"

    case "$mime_type" in
        application/x-debian-package|application/vnd.debian.binary-package)
            echo "Installing via dpkg..."
            dpkg -i "$file" || apt-get install -f -y
            ;;
        application/x-rpm)
            echo "Installing via rpm..."
            rpm -i "$file" || yum install -y "$file" || dnf install -y "$file"
            ;;
        text/x-shellscript|application/x-shellscript|application/x-sh)
            echo "Installing via shell script..."
            chmod +x "$file"
            echo "Script contents (first 20 lines):"
            head -20 "$file" || true
            echo "---"
            echo "File info:"
            file "$file" || true
            ls -la "$file" || true
            echo "---"
            echo "Running installer from /tmp directory..."
            cd /tmp
            # Run and capture output for debugging
            if ! bash "$file" 2>&1; then
                echo "Installer exited with non-zero status"
                echo "Checking for XDR processes anyway..."
                sleep 5  # Give agent time to start
                if pgrep -f "cortex|traps" > /dev/null 2>&1; then
                    echo "XDR agent appears to be running despite exit code"
                    exit 0
                fi
                # Check if installation directory exists
                if [ -d "/opt/traps" ] || [ -d "/opt/cortex" ]; then
                    echo "Installation directory exists, agent may be starting..."
                    exit 0
                fi
                exit 1
            fi
            ;;
        application/gzip|application/x-gzip)
            echo "Extracting gzip/tar.gz archive..."
            mkdir -p "$extract_dir"
            tar xzf "$file" -C "$extract_dir"
            run_extracted_installer "$extract_dir"
            ;;
        application/zip)
            echo "Extracting zip archive..."
            mkdir -p "$extract_dir"
            unzip -o "$file" -d "$extract_dir"
            run_extracted_installer "$extract_dir"
            ;;
        application/x-executable|application/octet-stream)
            # Could be a binary installer or unknown type
            # Try to detect by file extension or content
            if file "$file" | grep -q "gzip"; then
                echo "Detected gzip by content, extracting..."
                mkdir -p "$extract_dir"
                tar xzf "$file" -C "$extract_dir"
                run_extracted_installer "$extract_dir"
            elif file "$file" | grep -q "Zip"; then
                echo "Detected zip by content, extracting..."
                mkdir -p "$extract_dir"
                unzip -o "$file" -d "$extract_dir"
                run_extracted_installer "$extract_dir"
            else
                echo "Installing via executable..."
                chmod +x "$file"
                "$file" --install || "$file"
            fi
            ;;
        *)
            echo "Unknown installer type: $mime_type"
            echo "Attempting to run as executable..."
            chmod +x "$file"
            "$file" --install || "$file"
            ;;
    esac
}

# Run installation
install_agent "$installer_path"

echo "XDR agent installation complete"
exit 0
'''

# Bash script to verify XDR agent is running
VERIFY_XDR_SCRIPT = '''#!/bin/bash
set -euo pipefail

echo "Verifying Cortex XDR agent..."

# Check for Cortex XDR processes
if pgrep -f "cortex" > /dev/null 2>&1; then
    echo "Cortex process found"
    pgrep -af "cortex"
    exit 0
fi

# Check for Traps processes
if pgrep -f "traps" > /dev/null 2>&1; then
    echo "Traps process found"
    pgrep -af "traps"
    exit 0
fi

# Check systemd service
if systemctl is-active --quiet cortexagent 2>/dev/null; then
    echo "cortexagent service is running"
    exit 0
fi

if systemctl is-active --quiet traps 2>/dev/null; then
    echo "traps service is running"
    exit 0
fi

# Agent may still be initializing
echo "XDR agent process/service not found - agent may still be initializing"
exit 1
'''


class LinuxXDRAgentInstallPlan:
    """Setup plan for installing Cortex XDR agent on Linux instances.

    This plan downloads and installs the XDR agent from a presigned S3 URL.
    It supports multiple installer formats common in Linux environments.

    Steps:
    1. Download installer from presigned URL
    2. Detect format and install (deploys cortex.conf first for archives)

    Verification:
    - Check XDR process or service is running
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="download_xdr_agent",
            script=DOWNLOAD_XDR_SCRIPT,
            timeout_seconds=300,  # 5 min for download
        ),
        SetupStep(
            name="install_xdr_agent",
            script=INSTALL_XDR_SCRIPT,
            timeout_seconds=600,  # 10 min for install
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_xdr_agent",
        script=VERIFY_XDR_SCRIPT,
        timeout_seconds=120,  # 2 min for verification
        is_verification=True,
    )

    def get_context(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Get template variables for XDR install scripts.

        Args:
            config: Dict with agent_presigned_url

        Returns:
            Dict with agent_presigned_url

        Raises:
            ValueError: If agent_presigned_url is missing or empty
        """
        url = config.get("agent_presigned_url")
        if not url:
            raise ValueError(
                "config missing required key 'agent_presigned_url' for XDR install"
            )

        return {"agent_presigned_url": url}
