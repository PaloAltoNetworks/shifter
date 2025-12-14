# mcp-shifter Dockerfile
# Multi-stage build for minimal production image

# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files for dependency installation
COPY package*.json ./
COPY tsconfig.json ./

# Copy aptl-mcp-common for local dependency
COPY ../aptl-mcp-common /aptl-mcp-common

# Install dependencies
RUN npm ci

# Copy source code
COPY src ./src

# Build TypeScript
RUN npm run build

# Prune dev dependencies
RUN npm prune --production

# Production stage
FROM node:22-alpine

WORKDIR /app

# Copy built files and production dependencies
COPY --from=builder /app/build ./build
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

# Copy config example for reference
COPY config.example.json ./

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nodejs -u 1001

USER nodejs

# Environment variables (required at runtime)
ENV NODE_ENV=production
ENV PORT=3001

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://localhost:${PORT}/health || exit 1

EXPOSE 3001

CMD ["node", "build/index.js"]
