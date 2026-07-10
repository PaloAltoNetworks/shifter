# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT

# Backup-Alerts Module - RDS backup-failure detection (#160)
#
# Creates:
# - A dedicated CMK so the encrypted alert topic can receive RDS events
# - A KMS-encrypted SNS topic for RDS backup / availability / failure events
# - An RDS event subscription covering the supplied DB instances
#
# Why a dedicated CMK + topic instead of the shared `aws_sns_topic.alerts`:
# RDS reports backup and snapshot failures as RDS *events* (not CloudWatch
# metrics), delivered through an RDS event subscription. RDS publishes those
# events to SNS using the `events.rds.amazonaws.com` service principal, which
# must hold `kms:GenerateDataKey*` + `kms:Decrypt` on the topic's CMK. The
# shared alerts topic is encrypted with the AWS-managed `alias/aws/sns` key,
# whose policy cannot be edited to grant that principal, so RDS delivery to it
# silently fails. A dedicated customer-managed key keeps the publish grant off
# the shared alerting boundary. See docs/ops/disaster-recovery.md and AWS docs:
# https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html

data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Module = "backup-alerts"
  })
}

# ------------------------------------------------------------------------------
# CMK for the encrypted alert topic
# ------------------------------------------------------------------------------

resource "aws_kms_key" "this" {
  description             = "CMK for ${var.name_prefix} RDS backup-event SNS topic (#160)"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # Let the RDS event service generate the per-message data key and
        # decrypt it to deliver notifications to the encrypted topic.
        #
        # No aws:SourceArn / aws:SourceAccount confused-deputy condition: RDS
        # CreateEventSubscription performs an authorization test-publish through
        # the events.rds.amazonaws.com principal *before* the subscription
        # exists, so it carries no es: ARN and no source-account context. Any
        # condition therefore fails that test-publish with SNSNoAuthorization
        # and makes the subscription un-creatable (verified empirically on proof
        # with both aws:SourceAccount and aws:SourceArn forms). The grant is
        # instead bounded structurally: a single service principal acting only
        # on this account's own CMK (the key policy applies to this key alone),
        # used solely to deliver this account's RDS events to its own topic.
        Sid       = "AllowRdsEventsToUseKey"
        Effect    = "Allow"
        Principal = { Service = "events.rds.amazonaws.com" }
        Action = [
          "kms:GenerateDataKey*",
          "kms:Decrypt",
        ]
        Resource = "*"
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-backup-alerts"
  })
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.name_prefix}-backup-alerts"
  target_key_id = aws_kms_key.this.key_id
}

# ------------------------------------------------------------------------------
# Encrypted SNS topic for RDS backup events
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "this" {
  name              = "${var.name_prefix}-db-backup-alerts"
  kms_master_key_id = aws_kms_key.this.arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-db-backup-alerts"
  })
}

data "aws_iam_policy_document" "topic" {
  # Preserve owner control: a custom topic policy replaces the default, so the
  # account owner must keep full management of the topic.
  statement {
    sid    = "AllowAccountOwnerManagement"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions = [
      "SNS:GetTopicAttributes",
      "SNS:SetTopicAttributes",
      "SNS:AddPermission",
      "SNS:RemovePermission",
      "SNS:DeleteTopic",
      "SNS:Subscribe",
      "SNS:ListSubscriptionsByTopic",
      "SNS:Publish",
    ]
    resources = [aws_sns_topic.this.arn]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceOwner"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }

  # Let the RDS event service publish notifications to this topic.
  #
  # No aws:SourceArn / aws:SourceAccount confused-deputy condition: RDS
  # CreateEventSubscription runs an authorization test-publish through the
  # events.rds.amazonaws.com principal *before* the subscription exists, so the
  # publish carries no es: ARN and no source-account context. A condition on
  # this statement makes that test-publish fail with SNSNoAuthorization and the
  # subscription un-creatable (verified empirically on proof: both
  # aws:SourceAccount and aws:SourceArn forms produced SNSNoAuthorization).
  # The grant is bounded structurally instead: one service principal, one topic
  # ARN. Residual exposure if another account learns this exact topic ARN and
  # points its own RDS event subscription at it is limited to that account's RDS
  # event metadata arriving in this topic's ops inbox (noise) -- no read access
  # and no data exfiltration from this account.
  statement {
    sid    = "AllowRdsEventsToPublish"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.rds.amazonaws.com"]
    }
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.this.arn]
  }
}

resource "aws_sns_topic_policy" "this" {
  arn    = aws_sns_topic.this.arn
  policy = data.aws_iam_policy_document.topic.json
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.this.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ------------------------------------------------------------------------------
# RDS event subscription
# ------------------------------------------------------------------------------
# One subscription covers every supplied DB instance. The categories are the
# DR-relevant ones: a failed automated backup surfaces under "backup", storage
# exhaustion (which blocks backups) under "low storage", and engine/host
# failures under "failure"/"availability".

resource "aws_db_event_subscription" "this" {
  count = length(var.db_instance_identifiers) > 0 ? 1 : 0

  name        = "${var.name_prefix}-db-backup-events"
  sns_topic   = aws_sns_topic.this.arn
  source_type = "db-instance"
  source_ids  = var.db_instance_identifiers
  enabled     = true

  event_categories = [
    "availability",
    "backup",
    "failure",
    "low storage",
    "maintenance",
    "recovery",
  ]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-db-backup-events"
  })

  # The topic must accept RDS publishes before the subscription validates.
  depends_on = [aws_sns_topic_policy.this]
}
