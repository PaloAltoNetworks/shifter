// Proof environment Packer variables

aws_region    = "us-east-2"
instance_type = "t3.large"
ami_prefix    = "shifter"
// Fill in your target account's VPC/subnet IDs before running a Packer build.
// See docs/dev/deploy-secrets.md ("Fresh AWS account bootstrap order", step 3).
vpc_id        = "vpc-xxxxxxxxxxxxxxxxx"    // Default VPC in the target account
subnet_id     = "subnet-xxxxxxxxxxxxxxxxx" // public subnet (e.g. us-east-2a)
