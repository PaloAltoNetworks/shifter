variable "aws_region" {
  description = "AWS region for the CTFd instance"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "Portal VPC ID for the CTFd host"
  type        = string
}

variable "subnet_id" {
  description = "Public subnet ID for the CTFd host"
  type        = string
}

variable "ami_id" {
  description = "AMI ID for the CTFd instance"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for CTFd"
  type        = string
}

variable "root_volume_size" {
  description = "Root volume size in GB"
  type        = number
}

variable "root_volume_type" {
  description = "Root volume type"
  type        = string
}

variable "root_volume_iops" {
  description = "Root volume IOPS"
  type        = number
}

variable "root_volume_throughput" {
  description = "Root volume throughput in MiB/s"
  type        = number
}

variable "domain" {
  description = "Public DNS name for CTFd"
  type        = string
}

variable "ctfd_repo_url" {
  description = "CTFd git repository URL"
  type        = string
}

variable "ctfd_git_ref" {
  description = "Pinned CTFd git ref to deploy"
  type        = string
}

variable "docker_compose_version" {
  description = "Pinned Docker Compose release tag"
  type        = string
}

variable "docker_buildx_version" {
  description = "Pinned Docker Buildx release tag"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key material to import as an EC2 key pair"
  type        = string
  default     = ""
}

variable "ssh_allowed_cidrs" {
  description = "Map of SSH ingress descriptions to IPv4 CIDR blocks"
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Common tags to apply to resources"
  type        = map(string)
}
