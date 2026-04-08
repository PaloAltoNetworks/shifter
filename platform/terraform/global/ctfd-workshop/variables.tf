variable "aws_region" {
  description = "AWS region for the standalone workshop CTFd"
  type        = string
  default     = "us-east-2"
}

variable "subnet_id" {
  description = "Public subnet ID in the default VPC"
  type        = string
}

variable "ctfd_ami_id" {
  description = "AMI ID for the CTFd instance"
  type        = string
}

variable "instance_type" {
  description = "CTFd EC2 instance type"
  type        = string
  default     = "t3.xlarge"
}

variable "root_volume_size" {
  description = "Root volume size in GB"
  type        = number
  default     = 50
}

variable "root_volume_type" {
  description = "Root volume type"
  type        = string
  default     = "gp3"
}

variable "root_volume_iops" {
  description = "Root volume IOPS"
  type        = number
  default     = 3000
}

variable "root_volume_throughput" {
  description = "Root volume throughput in MiB/s"
  type        = number
  default     = 125
}

variable "domain" {
  description = "Public DNS name for the workshop CTFd"
  type        = string
  default     = "ctf.shifter.keplerops.com"
}

variable "ctfd_repo_url" {
  description = "CTFd git repository URL"
  type        = string
  default     = "https://github.com/CTFd/CTFd.git"
}

variable "ctfd_git_ref" {
  description = "Pinned CTFd git ref to deploy"
  type        = string
  default     = "b5f0cf2b7f0e29f72c9227ea9bc08024230b4f06"
}

variable "docker_compose_version" {
  description = "Pinned Docker Compose release tag"
  type        = string
  default     = "v5.1.0"
}
