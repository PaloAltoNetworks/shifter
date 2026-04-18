- subscribe to Kali
- Bedrock Opus 4.5 and Sonnet 4.5 request
- AMI packer builds or share between accounts

- bootstrap didn't wait between ACM creation and validation

add region to create first user section

aws --profile panw-shifter-prod-workstation cognito-idp admin-create-user --user-pool-id us-east-2_0WtqTp548 --username bedwards@paloaltonetworks.com --user-attributes Name=email,Value=bedwards@paloaltonetworks.com --desired-delivery-mediums EMAIL --region us-east-2

service level increase requests:

us.anthropic.claude-sonnet-4-5-20250929-v1:0 cross-region requests per minute -> 2000

global.anthropic.claude-haiku-4-5-20251001-v1:0 - > 2000


NGFW

- Add to XDR
- SCM, associate NGFW to account
- On NGFW, retrieve certificate
- Cert eventually validates

## Strata Logging Service / CDL Setup Commands

After associating the NGFW serial number with your tenant in Strata Cloud Manager:

```bash
# 1. Fetch the license (retrieves Logging Service license from CDL)
request license fetch

# 2. Enable cloud logging and set region (Canada = ca)
configure
set deviceconfig setting logging logging-service-forwarding enable yes
set deviceconfig setting logging logging-service-forwarding logging-service-regions ca
commit
exit

# 3. Verify configuration
show config running | match logging-service
```

Expected output after configuration:
```
logging-service-forwarding {
  enable yes;
  logging-service-regions ca;
}
```
