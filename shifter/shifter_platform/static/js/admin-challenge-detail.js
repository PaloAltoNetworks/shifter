// CTF admin challenge-detail page interactions: challenge-file downloads plus
// add/remove for flags, files, prerequisites, and hints.
//
// Extracted from the inline <script> blocks in
// templates/ctf/admin/challenge_detail.html so the template stays within
// Sonar's Web:LongJavaScriptCheck and Web:FileLengthCheck limits. The
// Django-interpolated endpoint URLs are passed in via the
// #admin-challenge-detail-config json_script payload; the CSRF token is read
// from the csrftoken cookie.

function getCookie(name) {
    if (!document.cookie) {
        return null;
    }
    const prefix = name + '=';
    const match = document.cookie
        .split(';')
        .map(function (part) { return part.trim(); })
        .find(function (part) { return part.startsWith(prefix); });
    return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

function readConfig() {
    const el = document.getElementById('admin-challenge-detail-config');
    return el ? JSON.parse(el.textContent) : {};
}

const config = readConfig();

// Placeholder id embedded in the reversed "remove" URLs; swapped for the real
// object id at call time.
const PLACEHOLDER_ID = '00000000-0000-0000-0000-000000000000';

function postJson(url, body) {
    const options = {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
    };
    if (body !== undefined) {
        options.body = JSON.stringify(body);
    }
    return fetch(url, options);
}

function reloadOrAlert(data) {
    if (data.error) { alert(data.error); } else { location.reload(); }
}

function downloadFile(apiUrl) {
    fetch(apiUrl, { headers: { 'X-CSRFToken': getCookie('csrftoken') } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.url) { globalThis.location.href = data.url; }
            else if (data.error) { alert(data.error); }
        })
        .catch(function () { alert('Download failed.'); });
}

document.querySelectorAll('[data-download-url]').forEach(function (link) {
    link.addEventListener('click', function (event) {
        event.preventDefault();
        downloadFile(link.dataset.downloadUrl);
    });
});

function addFlag() {
    const flagValue = document.getElementById('new-flag-value').value.trim();
    if (!flagValue) { alert('Flag value is required'); return; }
    const flagType = document.getElementById('new-flag-type').value;
    const caseSensitive = document.getElementById('new-flag-case-sensitive').value === 'true';
    postJson(config.addFlagUrl, { flag: flagValue, flag_type: flagType, case_sensitive: caseSensitive })
        .then(function (r) { return r.json(); })
        .then(reloadOrAlert);
}

function removeFlag(flagId) {
    if (!confirm('Remove this flag?')) return;
    postJson(config.removeFlagUrl.replace(PLACEHOLDER_ID, flagId))
        .then(function (r) { return r.json(); })
        .then(reloadOrAlert);
}

function removeFile(fileId) {
    if (!confirm('Remove this file?')) return;
    postJson(config.removeFileUrl.replace(PLACEHOLDER_ID, fileId))
        .then(function (r) { return r.json(); })
        .then(reloadOrAlert);
}

function addPrerequisite() {
    const challengeId = document.getElementById('prereq-challenge-select').value;
    if (!challengeId) { alert('Select a challenge'); return; }
    postJson(config.addPrerequisiteUrl, { required_challenge_id: challengeId })
        .then(function (r) { return r.json(); })
        .then(reloadOrAlert);
}

function removePrerequisite(prereqId) {
    if (!confirm('Remove this prerequisite?')) return;
    postJson(config.removePrerequisiteUrl.replace(PLACEHOLDER_ID, prereqId))
        .then(function (r) { return r.json(); })
        .then(reloadOrAlert);
}

function addHint() {
    const text = document.getElementById('new-hint-text').value.trim();
    const penalty = Number.parseInt(document.getElementById('new-hint-penalty').value, 10) || 0;
    const order = Number.parseInt(document.getElementById('new-hint-order').value, 10) || 0;
    if (!text) { alert('Hint text is required.'); return; }
    postJson(config.addHintUrl, { text: text, penalty: penalty, order: order })
        .then(function (r) { return r.json(); })
        .then(reloadOrAlert);
}

function removeHint(hintId) {
    if (!confirm('Remove this hint?')) return;
    postJson(config.removeHintUrl.replace(PLACEHOLDER_ID, hintId))
        .then(function (r) {
            if (r.ok) { location.reload(); } else { r.json().then(function (d) { alert(d.error); }); }
        });
}

globalThis.addFlag = addFlag;
globalThis.removeFlag = removeFlag;
globalThis.removeFile = removeFile;
globalThis.addPrerequisite = addPrerequisite;
globalThis.removePrerequisite = removePrerequisite;
globalThis.addHint = addHint;
globalThis.removeHint = removeHint;
