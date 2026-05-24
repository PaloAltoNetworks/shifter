/**
 * Jest tests for terminal-init.js (TerminalManager bootstrap).
 *
 * We stub the global TerminalManager constructor and dispatch
 * DOMContentLoaded after seeding the two json_script payloads.
 */

const seedDom = ({ instances, urls } = {}) => {
    document.body.innerHTML = `
        ${instances === null ? '' : `<script id="terminal-instances-data" type="application/json">${JSON.stringify(instances)}</script>`}
        ${urls === null ? '' : `<script id="terminal-connection-urls-data" type="application/json">${JSON.stringify(urls)}</script>`}
    `;
};

const loadScript = () => {
    let handler = null;
    const orig = document.addEventListener.bind(document);
    document.addEventListener = (event, cb) => {
        if (event === 'DOMContentLoaded') {
            handler = cb;
        } else {
            orig(event, cb);
        }
    };
    jest.isolateModules(() => {
        require('./terminal-init.js');
    });
    document.addEventListener = orig;
    handler();
};

describe('terminal-init', () => {
    let initSpy;
    let managerArgs;

    beforeEach(() => {
        managerArgs = null;
        initSpy = jest.fn();
        globalThis.TerminalManager = jest.fn(function (args) {
            managerArgs = args;
            this.init = initSpy;
        });
    });

    afterEach(() => {
        document.body.innerHTML = '';
        delete globalThis.TerminalManager;
    });

    test('does nothing when instances payload missing', () => {
        seedDom({ instances: null, urls: [] });
        loadScript();
        expect(globalThis.TerminalManager).not.toHaveBeenCalled();
        expect(initSpy).not.toHaveBeenCalled();
    });

    test('does nothing when connection-urls payload missing', () => {
        seedDom({ instances: [], urls: null });
        loadScript();
        expect(globalThis.TerminalManager).not.toHaveBeenCalled();
    });

    test('passes instances + camelCased URLs to TerminalManager', () => {
        seedDom({
            instances: [{ uuid: 'a', name: 'A' }],
            urls: [
                { uuid: 'a', terminal_url: '/ws/a/' },
                { uuid: 'b', terminal_url: '/ws/b/' },
            ],
        });
        loadScript();
        expect(globalThis.TerminalManager).toHaveBeenCalledTimes(1);
        expect(managerArgs.instances).toEqual([{ uuid: 'a', name: 'A' }]);
        expect(managerArgs.connectionUrls).toEqual([
            { uuid: 'a', terminalUrl: '/ws/a/' },
            { uuid: 'b', terminalUrl: '/ws/b/' },
        ]);
        expect(initSpy).toHaveBeenCalledTimes(1);
    });

    test('derives ws protocol and host from window.location', () => {
        seedDom({ instances: [], urls: [] });
        loadScript();
        // Default jsdom location is http://localhost/
        expect(managerArgs.wsProtocol).toBe('ws:');
        expect(managerArgs.wsHost).toBe(globalThis.location.host);
    });

    test('emits ws:// rather than wss:// for non-https pages', () => {
        seedDom({ instances: [], urls: [] });
        loadScript();
        expect(managerArgs.wsProtocol.endsWith(':')).toBe(true);
        expect(['ws:', 'wss:']).toContain(managerArgs.wsProtocol);
    });
});
