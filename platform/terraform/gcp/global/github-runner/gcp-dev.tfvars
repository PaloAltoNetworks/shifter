# Non-sensitive baseline for the gcp-dev runner root. project_id is supplied at
# apply time (-var=project_id=...) and is never committed. runner_version /
# runner_checksum pin the Actions runner; bump them together (the startup script
# verifies the checksum and fails closed on mismatch).
environment         = "gcp-dev"
region              = "us-central1"
zone                = "us-central1-a"
runner_count        = 1
machine_type        = "e2-standard-4"
runner_disk_size_gb = 100
runner_subnet_cidr  = "10.200.0.0/24"
runner_version      = "2.335.1"
runner_checksum     = "4ef2f25285f0ae4477f1fe1e346db76d2f3ebf03824e2ddd1973a2819bf6c8cf"
