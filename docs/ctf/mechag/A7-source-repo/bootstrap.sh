#!/bin/bash
set -e

# A7 Gitea Bootstrap Script
# Takes a fresh Gitea instance from zero to fully populated.
# Idempotent — safe to run multiple times.
#
# Prerequisites:
#   - Gitea binary available at $GITEA_BIN (default: /usr/local/bin/gitea)
#   - Gitea config at $GITEA_WORK_DIR/custom/conf/app.ini
#   - Gitea running and API responding
#   - Bare repo archives at $REPO_ARCHIVE_DIR (default: /opt/gitea-repos/)
#   - git installed
#
# Usage: ./bootstrap.sh

GITEA_BIN="${GITEA_BIN:-/usr/local/bin/gitea}"
GITEA_WORK_DIR="${GITEA_WORK_DIR:-/var/lib/gitea}"
GITEA_URL="${GITEA_URL:-http://localhost:3000}"
REPO_ARCHIVE_DIR="${REPO_ARCHIVE_DIR:-/opt/gitea-repos}"

ADMIN_USER="gitea_admin"
ADMIN_PASS="AdminPass123!"
ADMIN_EMAIL="admin@boreas.local"

API="${GITEA_URL}/api/v1"
AUTH="-u ${ADMIN_USER}:${ADMIN_PASS}"

log() { echo "[bootstrap] $*"; }
api() { curl -sf $AUTH "$@"; }
api_post() { curl -sf $AUTH -X POST -H "Content-Type: application/json" "$@"; }
api_put() { curl -sf $AUTH -X PUT "$@"; }
api_patch() { curl -sf $AUTH -X PATCH -H "Content-Type: application/json" "$@"; }

# ============================================
# Wait for Gitea to be ready
# ============================================
log "Waiting for Gitea API..."
for i in $(seq 1 60); do
    if curl -sf "${GITEA_URL}/api/v1/version" > /dev/null 2>&1; then
        log "Gitea API is ready"
        break
    fi
    sleep 2
done

# ============================================
# Create admin user (via CLI — works even before API auth is set up)
# ============================================
log "Creating admin user..."
# Run as git user if we're root (Gitea DB is owned by git)
if [ "$(id -u)" = "0" ]; then
    su -s /bin/sh git -c "GITEA_WORK_DIR=$GITEA_WORK_DIR $GITEA_BIN admin user create \
        --username $ADMIN_USER --password $ADMIN_PASS --email $ADMIN_EMAIL --admin" 2>/dev/null || log "Admin user already exists"
else
    GITEA_WORK_DIR="$GITEA_WORK_DIR" $GITEA_BIN admin user create \
        --username "$ADMIN_USER" --password "$ADMIN_PASS" --email "$ADMIN_EMAIL" --admin 2>/dev/null || log "Admin user already exists"
fi

# ============================================
# Create regular users
# ============================================
log "Creating users..."
for user_spec in \
    "e_vasik:TestPass123!:e.vasik@boreas.local" \
    "r_tanaka:TestPass123!:r.tanaka@boreas.local" \
    "m_webb:TestPass123!:m.webb@boreas.local" \
    "d_kowalski:TestPass123!:d.kowalski@boreas.local" \
    "p_nielsen:TestPass123!:p.nielsen@boreas.local" \
    "k_yamamoto:TestPass123!:k.yamamoto@boreas.local" \
    "f_okoye:TestPass123!:f.okoye@boreas.local"; do
    IFS=: read -r username password email_addr <<< "$user_spec"
    api_post "$API/admin/users" \
        -d "{\"username\":\"$username\",\"password\":\"$password\",\"email\":\"$email_addr\",\"must_change_password\":false}" \
        > /dev/null 2>&1 || true
    log "  User: $username"
done

# ============================================
# Create organizations
# ============================================
log "Creating organizations..."
api_post "$API/orgs" -d '{"username":"boreas-consulting","visibility":"public"}' > /dev/null 2>&1 || true
log "  Org: boreas-consulting (public)"

api_post "$API/orgs" -d '{"username":"aurora","visibility":"limited"}' > /dev/null 2>&1 || true
log "  Org: aurora (limited)"

# Change aurora to limited if it was created as private previously
api_patch "$API/orgs/aurora" -d '{"visibility":"limited"}' > /dev/null 2>&1 || true

# ============================================
# Create teams in aurora org
# ============================================
log "Creating teams..."

# Get existing team IDs
LAB_ID=""
PL_ID=""

# Create Lab-Access team
api_post "$API/orgs/aurora/teams" \
    -d '{"name":"Lab-Access","permission":"read","units":["repo.code","repo.issues","repo.pulls"],"includes_all_repositories":false}' \
    > /dev/null 2>&1 || true
LAB_ID=$(api "$API/orgs/aurora/teams" 2>/dev/null | python3 -c "import sys,json; [print(t['id']) for t in json.load(sys.stdin) if t['name']=='Lab-Access']" 2>/dev/null)
log "  Team: Lab-Access (id=$LAB_ID)"

# Create Project-L team
api_post "$API/orgs/aurora/teams" \
    -d '{"name":"Project-L","permission":"read","units":["repo.code","repo.issues"],"includes_all_repositories":false}' \
    > /dev/null 2>&1 || true
PL_ID=$(api "$API/orgs/aurora/teams" 2>/dev/null | python3 -c "import sys,json; [print(t['id']) for t in json.load(sys.stdin) if t['name']=='Project-L']" 2>/dev/null)
log "  Team: Project-L (id=$PL_ID)"

# ============================================
# Add users to teams
# ============================================
log "Adding users to teams..."
for user in e_vasik r_tanaka p_nielsen k_yamamoto f_okoye; do
    api_put "$API/teams/$LAB_ID/members/$user" > /dev/null 2>&1 || true
done
log "  Lab-Access: e_vasik, r_tanaka, p_nielsen, k_yamamoto, f_okoye"

api_put "$API/teams/$PL_ID/members/e_vasik" > /dev/null 2>&1 || true
log "  Project-L: e_vasik"

# ============================================
# Create repositories
# ============================================
log "Creating repositories..."

# boreas-consulting repos (public)
for repo in client-tools internal-docs; do
    api_post "$API/orgs/boreas-consulting/repos" \
        -d "{\"name\":\"$repo\",\"private\":false,\"auto_init\":false}" \
        > /dev/null 2>&1 || true
    log "  boreas-consulting/$repo (public)"
done

# aurora repos (private by default)
for repo in navigation-controller weapons-integration manufacturing-orchestrator; do
    api_post "$API/orgs/aurora/repos" \
        -d "{\"name\":\"$repo\",\"private\":true,\"auto_init\":false}" \
        > /dev/null 2>&1 || true
    log "  aurora/$repo (private)"
done

# leviathan-assembly (internal = misconfigured)
api_post "$API/orgs/aurora/repos" \
    -d '{"name":"leviathan-assembly","private":false,"auto_init":false}' \
    > /dev/null 2>&1 || true
api_patch "$API/repos/aurora/leviathan-assembly" \
    -d '{"private":false,"internal":true}' \
    > /dev/null 2>&1 || true
log "  aurora/leviathan-assembly (internal)"

# ============================================
# Add repos to teams
# ============================================
log "Adding repos to teams..."
api_put "$API/teams/$LAB_ID/repos/aurora/navigation-controller" > /dev/null 2>&1 || true
api_put "$API/teams/$LAB_ID/repos/aurora/manufacturing-orchestrator" > /dev/null 2>&1 || true
log "  Lab-Access: navigation-controller, manufacturing-orchestrator"

api_put "$API/teams/$PL_ID/repos/aurora/weapons-integration" > /dev/null 2>&1 || true
log "  Project-L: weapons-integration"

# ============================================
# Push bare repos
# ============================================
log "Pushing repo content..."

# Fix git safe.directory for repos owned by different user
git config --global --add safe.directory '*'

PUSH_URL="${GITEA_URL/http:\/\//http:\/\/${ADMIN_USER}:${ADMIN_PASS}@}"

REPO_MAP=(
    "boreas-consulting_client-tools.git:boreas-consulting/client-tools"
    "boreas-consulting_internal-docs.git:boreas-consulting/internal-docs"
    "aurora_navigation-controller.git:aurora/navigation-controller"
    "aurora_weapons-integration.git:aurora/weapons-integration"
    "aurora_manufacturing-orchestrator.git:aurora/manufacturing-orchestrator"
    "aurora_leviathan-assembly.git:aurora/leviathan-assembly"
)

for mapping in "${REPO_MAP[@]}"; do
    IFS=: read -r bare_name remote_path <<< "$mapping"
    bare_path="${REPO_ARCHIVE_DIR}/${bare_name}"

    if [ ! -d "$bare_path" ]; then
        log "  WARNING: $bare_path not found, skipping"
        continue
    fi

    # Check if repo already has commits
    COMMIT_COUNT=$(api "$API/repos/${remote_path}/commits?limit=1" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    if [ "$COMMIT_COUNT" != "0" ] && [ -n "$COMMIT_COUNT" ]; then
        log "  $remote_path: already has content, skipping push"
        continue
    fi

    cd "$bare_path"
    git remote remove gitea 2>/dev/null || true
    git remote add gitea "${PUSH_URL}/${remote_path}.git"
    git push gitea --all 2>&1 | tail -1
    log "  Pushed: $remote_path"
done

# ============================================
# Verify
# ============================================
log ""
log "=== Verification ==="
REPO_COUNT=$(api "$API/repos/search?limit=50" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null)
USER_COUNT=$(api "$API/admin/users" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
log "Users: $USER_COUNT"
log "Repos: $REPO_COUNT"
log ""
log "Bootstrap complete."
