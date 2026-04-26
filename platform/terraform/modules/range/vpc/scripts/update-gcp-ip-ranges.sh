#!/usr/bin/env bash
# DEPRECATED - DO NOT USE
#
# This script previously fetched ALL GCP IP ranges (cloud.json + goog.json)
# and used them as a firewall allowlist. This was incorrect — it allowed
# egress to all of Google/GCP instead of just PANW services.
#
# The victim_allowed_cidrs.auto.tfvars files now contain specific /32 IPs
# published by Palo Alto Networks for Cortex XSIAM/XDR.
#
# Source: https://docs-cortex.paloaltonetworks.com/r/Cortex-XSIAM/Cortex-XSIAM-Administrator-Guide/Resources-Required-to-Enable-Access
#
# To update the IP list, manually edit victim_allowed_cidrs.auto.tfvars
# based on the PANW documentation above.

echo "ERROR: This script is deprecated." >&2
echo ""
echo "The firewall allowlist now uses specific PANW-published IPs, not broad GCP ranges."
echo "To update, edit victim_allowed_cidrs.auto.tfvars manually from:"
echo "  https://docs-cortex.paloaltonetworks.com/r/Cortex-XSIAM/Cortex-XSIAM-Administrator-Guide/Resources-Required-to-Enable-Access"
exit 1
