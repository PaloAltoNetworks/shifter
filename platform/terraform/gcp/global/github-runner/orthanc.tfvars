# Legacy orthanc runner inputs. Preserve these names until its inventory cutover.
# The shared runner-release.auto.tfvars.json owns the version/checksum pin.
environment         = "orthanc"
region              = "us-central1"
zone                = "us-central1-a"
runner_count        = 1
machine_type        = "e2-standard-4"
runner_disk_size_gb = 100
runner_subnet_cidr  = "10.200.0.0/24"
