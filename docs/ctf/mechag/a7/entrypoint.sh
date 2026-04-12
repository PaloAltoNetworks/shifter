#!/bin/sh
# Start Gitea in background, then run bootstrap once data is ready

# Ensure data dirs exist with correct ownership
mkdir -p /data/gitea/conf /data/git/repositories
chown -R git:git /data
cat > /data/gitea/conf/app.ini << 'EOF'
[server]
HTTP_PORT = 3000
ROOT_URL = http://localhost:3000/
DISABLE_SSH = true

[database]
DB_TYPE = sqlite3
PATH = /data/gitea/gitea.db

[repository]
ROOT = /data/git/repositories

[security]
INSTALL_LOCK = true

[service]
DISABLE_REGISTRATION = true

[log]
MODE = console
LEVEL = Warn
EOF

# Extract bare repos
mkdir -p /app/repos
cd /app/repos && tar xzf /app/bare-repos.tar.gz
chown -R git:git /app/repos

# Start Gitea as git user
su -s /bin/sh git -c "/usr/local/bin/gitea web --config /data/gitea/conf/app.ini" &
GITEA_PID=$!

# Wait for Gitea to be ready, then bootstrap
sleep 8
GITEA_BIN=/usr/local/bin/gitea \
GITEA_WORK_DIR=/data/gitea \
GITEA_URL=http://localhost:3000 \
REPO_ARCHIVE_DIR=/app/repos \
/app/bootstrap.sh

# Keep running
wait $GITEA_PID
