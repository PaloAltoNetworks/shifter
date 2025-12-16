# Custom OpenWebUI image with Cortex Shifter theme
#
# Extends the official OpenWebUI image with:
# - Cortex XDR-style CSS theme
# - Custom logo and favicon
#
# Build: docker build -t shifter-openwebui .
# Run:   docker run -d -p 8080:8080 shifter-openwebui

FROM ghcr.io/open-webui/open-webui:v0.6.41

# Copy custom CSS theme
COPY custom-theme/custom.css /app/build/static/custom.css

# Copy logo to all paths OpenWebUI checks
COPY custom-theme/logo.png /app/backend/open_webui/static/logo.png
COPY custom-theme/logo.png /app/build/static/logo.png

# Copy favicon to all paths OpenWebUI checks
COPY custom-theme/favicon.png /app/backend/open_webui/static/favicon.png
COPY custom-theme/favicon.png /app/build/static/favicon.png
COPY custom-theme/favicon.png /app/build/favicon.png
COPY custom-theme/favicon.png /app/backend/open_webui/static/favicon.ico
COPY custom-theme/favicon.png /app/build/favicon.ico
