output "user_arns" {
  description = "Map of username to IAM user ARN"
  value = {
    for username, user in aws_iam_user.admin : username => user.arn
  }
}

output "passwords" {
  description = "Map of username to one-time console password (user must change on first login)"
  sensitive   = true
  value = {
    for username, profile in aws_iam_user_login_profile.admin : username => profile.password
  }
}

output "console_sign_in_url" {
  description = "AWS console sign-in URL for this account"
  value       = "https://454996813239.signin.aws.amazon.com/console"
}
