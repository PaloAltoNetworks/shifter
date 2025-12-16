# mcp-shifter Dockerfile
# Multi-stage build for minimal production image

# Build stage
FROM node:22-alpine AS builder

WORKDIR /build

# Copy and build aptl-mcp-common first
COPY aptl-mcp-common ./aptl-mcp-common
WORKDIR /build/aptl-mcp-common
RUN npm ci && npm run build

# Remove prepare script to prevent re-build during mcp-shifter install
RUN npm pkg delete scripts.prepare

# Now set up mcp-shifter
WORKDIR /build/mcp-shifter

# Copy package files (context is ./mcp)
COPY mcp-shifter/package*.json ./
COPY mcp-shifter/tsconfig.json ./

# Install dependencies - aptl-mcp-common is already built
RUN npm ci

# Copy source code and build
COPY mcp-shifter/src ./src
RUN npm run build

# Prune dev dependencies
RUN npm prune --production

# Production stage
FROM node:22-alpine

WORKDIR /app

# Copy aptl-mcp-common to where the symlink expects it
# Symlink: node_modules/aptl-mcp-common -> ../../aptl-mcp-common
# From /app/node_modules/, ../../aptl-mcp-common = /aptl-mcp-common
COPY --from=builder /build/aptl-mcp-common /aptl-mcp-common

# Copy built mcp-shifter files and dependencies
COPY --from=builder /build/mcp-shifter/build ./build
COPY --from=builder /build/mcp-shifter/node_modules ./node_modules
COPY --from=builder /build/mcp-shifter/package.json ./

# Copy config example for reference
COPY mcp-shifter/config.example.json ./

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nodejs -u 1001

USER nodejs

# Environment variables (required at runtime)
ENV NODE_ENV=production
ENV PORT=3001

# Health check - use node instead of wget for reliability on Alpine
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node -e "fetch('http://localhost:'+process.env.PORT+'/health').then(r=>{if(!r.ok)throw 1})" || exit 1

EXPOSE 3001

CMD ["node", "build/index.js"]
