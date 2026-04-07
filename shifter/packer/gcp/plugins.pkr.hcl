// Required Packer plugins for GCP/KubeVirt image builds.
//
// Uses the QEMU builder (not Amazon EBS) to produce qcow2 disk images
// that are wrapped in OCI containers and pushed to Artifact Registry
// for use as KubeVirt containerDisk volumes.

packer {
  required_plugins {
    qemu = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/qemu"
    }
  }
}
