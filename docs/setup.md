# Setup

## Prerequisites

- Node.js 22.x
- Python 3.11+
- Terraform 1.14+
- AWS CLI configured with SSO
- GitHub CLI (`gh`) for secrets sync

## Infrastructure Deployment

### First-Time Setup

1. Configure AWS SSO and login:
   ```bash
   aws sso login
   ```

2. Create `terraform.tfvars` from example:
   ```bash
   cp terraform/environments/prod/portal/terraform.tfvars.example \
      terraform/environments/prod/portal/terraform.tfvars
   ```

3. Fill in values, then sync to GitHub secrets:
   ```bash
   ./scripts/sync-tfvars.sh
   ```

4. Push branch and create PR. GitHub Actions runs `terraform plan`.

5. Merge to main. GitHub Actions runs `terraform apply`.

### Manual Deployment

Via workflow dispatch in GitHub Actions, or locally:

```bash
cd terraform/environments/prod/portal
terraform init
terraform plan
terraform apply
```

## MCP Development

### aptl-mcp-common

```bash
cd mcp/aptl-mcp-common
npm install
npm run build
npm test -- --coverage
```

### mcp-red

```bash
cd mcp/mcp-red
npm install
npm run build
npx @modelcontextprotocol/inspector build/index.js
```

## Documentation

### Local Preview

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

Browse to `http://127.0.0.1:8000`

### Deploy to GitHub Pages

Automatic via GitHub Actions on push to `main`.
