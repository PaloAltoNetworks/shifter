#!/bin/bash
# LocalStack initialization script for local development
# Creates S3 bucket for agent uploads and Terraform state

set -e

echo "Initializing LocalStack resources..."

REGION="us-east-2"

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

echo "LocalStack initialization complete!"
echo "  S3 Bucket: shifter-assets"
