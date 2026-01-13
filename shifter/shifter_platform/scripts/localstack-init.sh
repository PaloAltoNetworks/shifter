#!/bin/bash
# LocalStack initialization script for local development
# Creates SNS topic + SQS queues + subscriptions to mirror production setup

set -e

echo "Initializing LocalStack resources..."

REGION="us-east-2"
ENDPOINT="http://localhost:4566"

# Create S3 bucket for agent uploads
echo "Creating S3 bucket: shifter-assets"
awslocal s3 mb s3://shifter-assets --region $REGION

# Configure CORS for browser uploads
echo "Configuring S3 bucket CORS..."
awslocal s3api put-bucket-cors --bucket shifter-assets --cors-configuration '{
  "CORSRules": [{
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET", "PUT", "POST"],
    "AllowedHeaders": ["*"]
  }]
}'

# Create SNS topic for range events
echo "Creating SNS topic: shifter-range-events"
awslocal sns create-topic --name shifter-range-events --region $REGION

# Create SQS queues for each worker
echo "Creating SQS queues..."
awslocal sqs create-queue --queue-name shifter-cms --region $REGION
awslocal sqs create-queue --queue-name shifter-engine --region $REGION
awslocal sqs create-queue --queue-name shifter-mc --region $REGION

# Get ARNs
SNS_ARN="arn:aws:sns:${REGION}:000000000000:shifter-range-events"
CMS_ARN="arn:aws:sqs:${REGION}:000000000000:shifter-cms"
ENGINE_ARN="arn:aws:sqs:${REGION}:000000000000:shifter-engine"
MC_ARN="arn:aws:sqs:${REGION}:000000000000:shifter-mc"

# Subscribe SQS queues to SNS topic (fan-out pattern)
echo "Subscribing queues to SNS topic..."
awslocal sns subscribe \
    --topic-arn $SNS_ARN \
    --protocol sqs \
    --notification-endpoint $CMS_ARN \
    --region $REGION

awslocal sns subscribe \
    --topic-arn $SNS_ARN \
    --protocol sqs \
    --notification-endpoint $ENGINE_ARN \
    --region $REGION

awslocal sns subscribe \
    --topic-arn $SNS_ARN \
    --protocol sqs \
    --notification-endpoint $MC_ARN \
    --region $REGION

echo "LocalStack initialization complete!"
echo "  SNS Topic: $SNS_ARN"
echo "  SQS CMS:   $CMS_ARN"
echo "  SQS Engine: $ENGINE_ARN"
echo "  SQS MC:    $MC_ARN"
