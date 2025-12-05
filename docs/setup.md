# Setup

## Prerequisites

- Node.js 22.x
- Python 3.11+
- AWS CLI configured

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
