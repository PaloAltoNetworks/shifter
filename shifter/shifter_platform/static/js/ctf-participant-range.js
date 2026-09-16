// CTF participant range-access page: open a Guacamole RDP session for a
// target box and poll until the broker returns a session URL.
//
// Extracted from the inline <script> block in
// templates/ctf/participant/range.html so the template stays within
// Sonar's Web:LongJavaScriptCheck limit. The Django-interpolated RDP
// endpoint URL is passed in via the #ctf-participant-range-config
// json_script payload.

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
    const el = document.getElementById('ctf-participant-range-config');
    return el ? JSON.parse(el.textContent) : {};
}

const config = readConfig();

function pollRdpSession(statusUrl, attemptsRemaining) {
    return fetch(statusUrl, { credentials: 'same-origin' })
        .then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) {
                    throw new Error(data.error || 'Failed to generate access URL');
                }
                if (data.url) {
                    return data.url;
                }
                if (data.error) {
                    throw new Error(data.error);
                }
                if (attemptsRemaining <= 1) {
                    throw new Error('RDP session request timed out');
                }
                return new Promise(function (resolve) {
                    globalThis.setTimeout(resolve, 1000);
                }).then(function () {
                    return pollRdpSession(statusUrl, attemptsRemaining - 1);
                });
            });
        });
}

function openRdpSession(button, instanceUuid) {
    if (!instanceUuid) {
        alert('Instance not available');
        return;
    }

    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = 'Opening...';
    const sessionWindow = window.open('about:blank', '_blank');
    if (sessionWindow) {
        sessionWindow.opener = null;
    }

    fetch(config.rdpUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ instance_uuid: instanceUuid }),
    })
    .then(function (response) {
        if (!response.ok) {
            return response.json().then(function (data) {
                throw new Error(data.error || 'Failed to generate access URL');
            });
        }
        return response.json();
    })
    .then(function (data) {
        if (!data.status_url) {
            throw new Error('Session request did not return a status URL');
        }
        return pollRdpSession(data.status_url, 60);
    })
    .then(function (url) {
        if (sessionWindow) {
            sessionWindow.location.replace(url);
        } else {
            window.open(url, '_blank', 'noopener,noreferrer');
        }
    })
    .catch(function (error) {
        if (sessionWindow) {
            sessionWindow.close();
        }
        alert('Failed to open session: ' + error.message);
    })
    .finally(function () {
        button.disabled = false;
        button.textContent = originalText;
    });
}

globalThis.openRdpSession = openRdpSession;
