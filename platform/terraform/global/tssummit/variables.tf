variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "ami_id" {
  description = "AMI ID for WebServer1 (migrated from original instance)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t2.micro"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = "tssummitwebserver"
}

variable "subnet_id" {
  description = "Subnet ID in the default VPC"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "Map of description to CIDR for SSH ingress rules"
  type        = map(string)
}

variable "ctfd_ami_id" {
  description = "AMI ID for the CTFd instance"
  type        = string
}
