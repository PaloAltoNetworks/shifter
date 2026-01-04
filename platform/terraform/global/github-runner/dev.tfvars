environment = "dev"
vpc_id      = "vpc-0eb7ca67e9f22929a" # Default VPC

github_org  = "Brad-Edwards"
github_repo = "shifter"

# GitHub App configuration
github_app_id = "2594040"

# Runner scaling
runners_maximum_count = 5
instance_types        = ["t3.large", "t3.xlarge"]
