# Credentials

Manage authentication credentials for NGFW integration.

## When You Need Credentials

Credentials are only required for NGFW scenarios. If you're using Basic Range or AD Attack Lab without NGFW, skip this section.

## Credential Types

### SCM Credentials

For Strata Cloud Manager device association.

| Field | Description |
|-------|-------------|
| Folder Name | Folder in SCM where device will be registered |
| PIN ID | Registration PIN identifier |
| PIN Value | Secret PIN value (encrypted at rest) |
| License Region | Strata Logging Service region |

### Deployment Profiles

For software NGFW deployment.

| Field | Description |
|-------|-------------|
| Authcode | License authorization code |

## Add Credentials

1. Go to **Assets > Credentials**
2. Click **Add Credential**
3. Select credential type
4. Fill in required fields
5. Save

## Expiration

Credentials track expiration dates:

- **Valid**: Credential is current
- **Expires Soon**: Within 30 days of expiration
- **Expired**: No longer valid, needs renewal

## Manage Credentials

From the Credentials page:

- View all credentials with type badges
- Filter by type (All, SCM, Deployment Profiles)
- See expiration status
- Delete credentials

## Where to Get These Values

**SCM Credentials**: From your Strata Cloud Manager console under device onboarding.

**Deployment Profiles**: From your PANW license portal or account team.
