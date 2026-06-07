/**
 * Guacamole RDP/SSH session bootstrap for the terminal page.
 *
 * Loads its CSRF token + per-protocol endpoint URLs from a json_script
 * payload (id="terminal-guacamole-config") so the template doesn't need
 * inline JS for the click-handler wiring. Sonar's `Web:LongJavaScriptCheck`
 * (issue #370) flagged the previous inline implementation.
 */
const BOOTSTRAP_POLL_INTERVAL_MS = 1000;
const BOOTSTRAP_POLL_ATTEMPTS = 60;

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function readJson(response) {
    try {
        return await response.json();
    } catch {
        return {};
    }
}

async function pollGuacamoleBootstrap(statusUrl, sessionLabel) {
    for (let attempt = 0; attempt < BOOTSTRAP_POLL_ATTEMPTS; attempt += 1) {
        const response = await fetch(statusUrl, {
            headers: { 'Accept': 'application/json' },
        });
        const data = await readJson(response);
        if (!response.ok) {
            throw new Error(data.error || `Failed to generate ${sessionLabel} URL`);
        }
        if (data.url) {
            return data.url;
        }
        await delay(BOOTSTRAP_POLL_INTERVAL_MS);
    }
    throw new Error(`${sessionLabel} session request timed out`);
}

async function resolveGuacamoleUrl(data, sessionLabel) {
    if (data.status_url) {
        return pollGuacamoleBootstrap(data.status_url, sessionLabel);
    }
    if (data.url) {
        return data.url;
    }
    throw new Error('Server returned invalid response');
}

async function openGuacamoleSession(button, instanceUuid, endpointUrl, sessionLabel, csrfToken) {
    if (!instanceUuid) {
        alert('Instance not available');
        return;
    }

    button.disabled = true;
    button.classList.add('loading');

    try {
        const response = await fetch(endpointUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({ instance_uuid: instanceUuid }),
        });

        const data = await readJson(response);
        if (!response.ok) {
            throw new Error(data.error || `Failed to generate ${sessionLabel} URL`);
        }

        const sessionUrl = await resolveGuacamoleUrl(data, sessionLabel);
        const popup = globalThis.open(sessionUrl, '_blank');
        if (!popup || popup.closed || popup.closed === undefined) {
            if (confirm(`Popup blocked. Click OK to open the ${sessionLabel} session in this tab.`)) {
                globalThis.location.href = sessionUrl;
            } else {
                throw new Error('Popup blocked by browser');
            }
        }
    } catch (error) {
        console.error(`${sessionLabel} button error:`, error);
        alert(`Failed to open ${sessionLabel} session: ${error.message}`);
    } finally {
        button.disabled = false;
        button.classList.remove('loading');
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const configEl = document.getElementById('terminal-guacamole-config');
    if (!configEl) {
        return;
    }
    const config = JSON.parse(configEl.textContent);
    const { rdpUrl, sshUrl, csrfToken } = config;

    const openRdp = (button, uuid) => openGuacamoleSession(button, uuid, rdpUrl, 'RDP', csrfToken);
    const openSsh = (button, uuid) => openGuacamoleSession(button, uuid, sshUrl, 'SSH', csrfToken);

    document.querySelectorAll('.ssh-btn[data-uuid]').forEach(btn => {
        btn.addEventListener('click', e => {
            const button = e.currentTarget;
            openSsh(button, button.dataset.uuid);
        });
    });
    document.querySelectorAll('.rdp-btn[data-uuid]').forEach(btn => {
        btn.addEventListener('click', e => {
            const button = e.currentTarget;
            openRdp(button, button.dataset.uuid);
        });
    });

    const splitWire = (btnId, selectId, opener) => {
        document.getElementById(btnId)?.addEventListener('click', e => {
            const select = document.getElementById(selectId);
            opener(e.currentTarget, select?.value);
        });
    };
    splitWire('left-pane-ssh-btn', 'left-pane-select', openSsh);
    splitWire('left-pane-rdp-btn', 'left-pane-select', openRdp);
    splitWire('right-pane-ssh-btn', 'right-pane-select', openSsh);
    splitWire('right-pane-rdp-btn', 'right-pane-select', openRdp);
});
