// Plugin requirements for the GCE (googlecompute) image builders.
//
// All *.pkr.hcl files in this directory are evaluated as a single Packer
// configuration, so the plugin only needs to be declared once here. The AWS
// builders one directory up (shifter/packer/*.pkr.hcl) are a SEPARATE
// configuration and are never read by `packer` invoked in this directory
// (Packer does not recurse), so the AWS amazon-ebs flow is unaffected.
packer {
  required_plugins {
    googlecompute = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/googlecompute"
    }
  }
}
