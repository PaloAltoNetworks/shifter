# Polaris CTF pre-promoted DC profile -> image family shifter-polaris-dc.
# Built by dc-prebaked.pkr.hcl. Domain BOREAS.LOCAL, seeded with the Polaris AD
# content (shared with the AWS Polaris build).
dc_image_purpose  = "polaris"
dc_domain_name    = "boreas.local"
dc_netbios_name   = "BOREAS"
dc_content_script = "../scripts/windows/polaris-content-seed.ps1"
