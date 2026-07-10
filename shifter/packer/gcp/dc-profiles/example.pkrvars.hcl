# Template for a new pre-promoted DC image. To add a DC for a new domain:
#   1. Copy this file to dc-profiles/<name>.pkrvars.hcl and edit the values.
#   2. Add the AD-content seed script it points at (accepts -DnsForwarder).
#   3. Run the "Packer GCE Image Build" workflow with image_type=dc-prebaked and
#      dc_profile=<name>.
# This produces image family shifter-<purpose>-dc. See
# docs/dev/gcp-range-cell-deploy.md ("Baking a new pre-promoted DC image").
dc_image_purpose = "example"
dc_domain_name   = "example.local"
dc_netbios_name  = "EXAMPLE"
# Path relative to shifter/packer/gcp. Seeds this scenario's AD content
# (OUs/users/groups/SPNs) and sets the CTF Administrator password.
dc_content_script = "../../../scripts/example-range/a2_setup.ps1"
