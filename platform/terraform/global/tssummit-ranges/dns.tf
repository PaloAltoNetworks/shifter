# ------------------------------------------------------------------------------
# Private DNS Records (shifter.local)
# ------------------------------------------------------------------------------
# Stable FQDNs for ZTNA connector access via Prisma Access browser.
# Zone created externally; each team adds its own records.
# Records: webserver.team2.shifter.local, winserver.team2.shifter.local, etc.
# ------------------------------------------------------------------------------

data "aws_route53_zone" "private" {
  name         = "shifter.local"
  private_zone = true
}

locals {
  team_lower = lower(var.team_name)
}

resource "aws_route53_record" "webserver" {
  zone_id = data.aws_route53_zone.private.zone_id
  name    = "webserver.${local.team_lower}.shifter.local"
  type    = "A"
  ttl     = 60
  records = [aws_instance.webserver.private_ip]
}

resource "aws_route53_record" "winserver" {
  zone_id = data.aws_route53_zone.private.zone_id
  name    = "winserver.${local.team_lower}.shifter.local"
  type    = "A"
  ttl     = 60
  records = [aws_instance.windows_server.private_ip]
}

resource "aws_route53_record" "windesktop" {
  zone_id = data.aws_route53_zone.private.zone_id
  name    = "windesktop.${local.team_lower}.shifter.local"
  type    = "A"
  ttl     = 60
  records = [aws_instance.windows_desktop.private_ip]
}

resource "aws_route53_record" "workstation" {
  zone_id = data.aws_route53_zone.private.zone_id
  name    = "workstation.${local.team_lower}.shifter.local"
  type    = "A"
  ttl     = 60
  records = [aws_instance.workstation.private_ip]
}
