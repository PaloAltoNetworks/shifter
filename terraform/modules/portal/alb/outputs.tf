output "alb_dns_name" {
  description = "DNS name of the ALB (create CNAME pointing to this)"
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "Route53 zone ID of the ALB (for Alias records)"
  value       = aws_lb.this.zone_id
}

output "alb_arn" {
  description = "ARN of the ALB"
  value       = aws_lb.this.arn
}

output "security_group_id" {
  description = "Security group ID of the ALB"
  value       = aws_security_group.this.id
}

output "target_group_arn" {
  description = "ARN of the target group"
  value       = aws_lb_target_group.this.arn
}

output "acm_certificate_arn" {
  description = "ARN of the ACM certificate"
  value       = aws_acm_certificate.this.arn
}

output "acm_validation_records" {
  description = "DNS records to create for ACM certificate validation"
  value = {
    for dvo in aws_acm_certificate.this.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
}
