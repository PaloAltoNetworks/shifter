#!/usr/bin/env bash
# A7 Gitea Source Repo smoketest.
#
# Runs every flag path from an attacker's perspective. Intended to be
# executed from inside the a14-kali container. A7 is multi-homed on
# shared + lab networks; a14-kali reaches it directly via the shared
# network (git.boreas.local:3000).
#
# Usage (from the range host):
#     docker cp smoketest.sh a14-kali:/tmp/a7-smoke.sh
#     docker exec a14-kali bash /tmp/a7-smoke.sh
#
# Uses ~/.netrc for git auth so passwords containing # and @ work
# without URL-encoding gymnastics.
#
# Exits 0 on full pass, 1 on any failure.

set -u

HOST="${A7_HOST:-git.boreas.local}"
BASE_URL="http://${HOST}:3000"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

# Reuse of AD passwords (post-fix — see CHANGELOG for the bootstrap.sh update
# that made Gitea passwords match A1/A2/A6 AD credentials)
LAB_USER="e_vasik"
LAB_PASS='Reactor#Core9'

EXPECTED_FLAG_24="FLAG{8a0e3c7f2d5b1946}"
EXPECTED_FLAG_29="FLAG{1f9b4e7c0a3d8265}"
EXPECTED_PASSPHRASE="Pr0m3th3us_Unb0und_2024"

urlenc() { python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"; }
git_clone_auth() {
    local user="$1" pass="$2" path="$3" dir="$4"
    local enc_pass
    enc_pass="$(urlenc "$pass")"
    git clone -q "http://${user}:${enc_pass}@${HOST}:3000/${path}" "$dir" 2>&1
}
ls_remote_auth() {
    local user="$1" pass="$2" path="$3"
    local enc_pass
    enc_pass="$(urlenc "$pass")"
    git ls-remote "http://${user}:${enc_pass}@${HOST}:3000/${path}" HEAD
}

FAIL=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }
check_flag() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$actual" == *"$expected"* ]]; then
        pass "$label = $expected"
    else
        fail "$label expected=$expected got='$actual'"
    fi
}

echo "A7 smoketest - target=$HOST"

echo
echo "--- Gitea API reachable ---"
ver="$(curl -sf "$BASE_URL/api/v1/version" 2>&1)"
grep -q '"version"' <<<"$ver" && pass "Gitea API responds: $ver" || fail "Gitea API not reachable"

echo
echo "--- Public orgs + repos discoverable anonymously ---"
anon_orgs="$(curl -sf "$BASE_URL/api/v1/orgs?limit=50")"
grep -q '"boreas-consulting"' <<<"$anon_orgs" && pass "boreas-consulting org visible anonymously" || fail "boreas-consulting missing from anonymous org list"
if grep -q '"aurora"' <<<"$anon_orgs"; then
    fail "aurora org visible anonymously (should be limited visibility)"
else
    pass "aurora org correctly hidden from anonymous listing (limited visibility)"
fi
public_repos="$(curl -sf "$BASE_URL/api/v1/repos/search?limit=50")"
grep -q '"client-tools"' <<<"$public_repos" && pass "boreas-consulting/client-tools discoverable (public)" || fail "client-tools not discoverable"
grep -q '"internal-docs"' <<<"$public_repos" && pass "boreas-consulting/internal-docs discoverable (public)" || fail "internal-docs not discoverable"
aurora_anon="$(curl -sf "$BASE_URL/api/v1/orgs/aurora/repos" 2>&1)"
grep -q '"navigation-controller"' <<<"$aurora_anon" && fail "aurora repos visible anonymously" || pass "aurora repos hidden from anonymous listing"

echo
echo "--- Anonymous clone of public repo ---"
if git clone -q "$BASE_URL/boreas-consulting/internal-docs.git" internal-docs 2>/dev/null && [[ -f internal-docs/README.md ]]; then
    pass "anonymous clone of internal-docs works"
else
    fail "anonymous clone of internal-docs failed"
fi

echo
echo "--- Anonymous clone of PRIVATE repo must fail ---"
if git clone -q "$BASE_URL/aurora/navigation-controller.git" nav-anon 2>/dev/null; then
    fail "anonymous clone of navigation-controller should have failed"
else
    pass "anonymous clone of navigation-controller denied"
fi

echo
echo "--- Authenticated clone: navigation-controller (Lab-Access) ---"
if git_clone_auth "$LAB_USER" "$LAB_PASS" "aurora/navigation-controller.git" navigation-controller >/dev/null 2>&1; then
    pass "$LAB_USER clones navigation-controller"
else
    fail "$LAB_USER failed to clone navigation-controller"
fi

echo
echo "--- Flag 24: git log -p deploy token from removed commit ---"
if [[ -d navigation-controller ]]; then
    cd navigation-controller
    flag24="$(git log --all -p 2>&1 | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
    check_flag "flag 24" "$EXPECTED_FLAG_24" "$flag24"
    cd ..
fi

echo
echo "--- Authenticated clone: weapons-integration (Project-L) ---"
if git_clone_auth "$LAB_USER" "$LAB_PASS" "aurora/weapons-integration.git" weapons-integration >/dev/null 2>&1; then
    pass "$LAB_USER clones weapons-integration"
    passphrase_line="$(grep -hE 'LEGACY_PASSPHRASE' weapons-integration/src/crypto_config.py 2>/dev/null)"
    if [[ "$passphrase_line" == *"$EXPECTED_PASSPHRASE"* ]]; then
        pass "LEGACY_PASSPHRASE present (A6 flag 30 GPG cross-asset breadcrumb)"
    else
        fail "LEGACY_PASSPHRASE not found - got '$passphrase_line'"
    fi
else
    fail "$LAB_USER failed to clone weapons-integration"
fi

echo
echo "--- Authenticated clone: manufacturing-orchestrator ---"
if git_clone_auth "$LAB_USER" "$LAB_PASS" "aurora/manufacturing-orchestrator.git" manufacturing-orchestrator >/dev/null 2>&1; then
    pass "$LAB_USER clones manufacturing-orchestrator"
    [[ -f manufacturing-orchestrator/playbooks/deploy_combat_ai.yml ]] \
        && pass "deploy_combat_ai.yml playbook present" \
        || fail "deploy_combat_ai.yml missing"
else
    fail "manufacturing-orchestrator clone failed"
fi

echo
echo "--- Internal-visibility clone: leviathan-assembly ---"
if git_clone_auth "$LAB_USER" "$LAB_PASS" "aurora/leviathan-assembly.git" leviathan-assembly >/dev/null 2>&1; then
    pass "$LAB_USER clones leviathan-assembly (internal visibility = the misconfig)"
else
    fail "leviathan-assembly clone failed"
fi

echo
echo "--- Flag 29: recover deleted schematic.svg from history ---"
if [[ -d leviathan-assembly ]]; then
    cd leviathan-assembly
    head_readme="$(cat README.md 2>/dev/null)"
    grep -q 'secure system' <<<"$head_readme" && pass "current HEAD README says moved to secure system" || fail "head README wrong"
    del_commit="$(git log --all --diff-filter=D --pretty=format:'%H' -- schematic.svg 2>/dev/null | head -1)"
    [[ -n "$del_commit" ]] && pass "found deletion commit $del_commit" || fail "deletion commit not found"
    if [[ -n "$del_commit" ]]; then
        flag29="$(git show "${del_commit}^:schematic.svg" 2>/dev/null | grep -oE 'FLAG\{[a-f0-9]+\}' | head -1)"
        check_flag "flag 29" "$EXPECTED_FLAG_29" "$flag29"
    fi
    cd ..
fi

echo
echo "--- Password-reuse validation: other Lab-Access users ---"
for u_p in "r_tanaka:SimEngine#42" "p_nielsen:Hydraulics1"; do
    u="${u_p%%:*}"
    p="${u_p#*:}"
    if ls_remote_auth "$u" "$p" "aurora/navigation-controller.git" >/dev/null 2>&1; then
        pass "$u AD-pattern password reuse works"
    else
        fail "$u cannot auth to gitea"
    fi
done

echo
if (( FAIL == 0 )); then
    echo "A7 smoketest: PASS"
    exit 0
else
    echo "A7 smoketest: FAIL ($FAIL failure(s))"
    exit 1
fi
