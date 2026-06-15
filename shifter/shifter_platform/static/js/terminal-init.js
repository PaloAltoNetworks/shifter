/**
 * Bootstraps TerminalManager from the page-embedded json_script payload.
 *
 * The Django template renders two json_script blocks
 * (`terminal-instances-data` and `terminal-connection-urls-data`); this file
 * parses them on DOMContentLoaded and wires the TerminalManager instance.
 *
 * Inline boot scripts get flagged by SonarCloud's `Web:LongJavaScriptCheck`
 * once they grow beyond a handful of lines, hence the extraction.
 */
/* global TerminalManager */

document.addEventListener('DOMContentLoaded', function () {
    const instancesEl = document.getElementById('terminal-instances-data');
    const connectionUrlsEl = document.getElementById('terminal-connection-urls-data');
    if (!instancesEl || !connectionUrlsEl) {
        return;
    }

    const instances = JSON.parse(instancesEl.textContent);
    const rawConnectionUrls = JSON.parse(connectionUrlsEl.textContent);
    const connectionUrls = rawConnectionUrls.map(function (conn) {
        return { uuid: conn.uuid, terminalUrl: conn.terminal_url };
    });

    const location = globalThis.location;
    const terminalManager = new TerminalManager({
        instances: instances,
        connectionUrls: connectionUrls,
        wsProtocol: location.protocol === 'https:' ? 'wss:' : 'ws:',
        wsHost: location.host,
    });
    terminalManager.init();
});
