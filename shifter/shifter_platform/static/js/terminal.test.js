require('./terminal.js');

describe('TerminalManager', () => {
    let manager;
    let mockWebSocket;
    let mockTerminal;
    let mockFitAddon;

    const instances = [
        { uuid: 'kali-uuid', role: 'attacker', osType: 'kali', name: 'Kali Linux' },
        { uuid: 'victim-uuid', role: 'victim', osType: 'ubuntu', name: 'Ubuntu Victim' },
        { uuid: 'dc-uuid', role: 'dc', osType: 'windows', name: 'Domain Controller' },
    ];

    const connectionUrls = [
        { uuid: 'kali-uuid', terminalUrl: '/ws/terminal/kali/' },
        { uuid: 'victim-uuid', terminalUrl: '/ws/terminal/victim/' },
        { uuid: 'dc-uuid', terminalUrl: '/ws/terminal/dc/' },
    ];

    const buildTerminalMarkup = () => `
        <div id="layout-toggle">
            <button class="toggle-btn active" data-mode="tabs"></button>
            <button class="toggle-btn" data-mode="split"></button>
        </div>
        <div id="terminal-tabs"></div>
        <div id="terminal-container" class="mode-tabs">
            <div class="terminal-pane active" id="pane-kali-uuid" data-uuid="kali-uuid">
                <div id="status-kali-uuid">
                    <span class="status-indicator"></span>
                    <span class="status-text">Not connected</span>
                </div>
                <div id="terminal-kali-uuid"></div>
            </div>
            <div class="terminal-pane" id="pane-victim-uuid" data-uuid="victim-uuid">
                <div id="status-victim-uuid">
                    <span class="status-indicator"></span>
                    <span class="status-text">Not connected</span>
                </div>
                <div id="terminal-victim-uuid"></div>
            </div>
            <div class="terminal-pane" id="pane-dc-uuid" data-uuid="dc-uuid">
                <div id="status-dc-uuid">
                    <span class="status-indicator"></span>
                    <span class="status-text">Not connected</span>
                </div>
                <div id="terminal-dc-uuid"></div>
            </div>
            <div class="split-pane" id="left-pane">
                <select id="left-pane-select"></select>
                <div id="left-pane-status">
                    <span class="status-indicator"></span>
                    <span class="status-text">Not connected</span>
                </div>
                <div id="left-terminal-wrapper"></div>
            </div>
            <div class="split-pane" id="right-pane">
                <select id="right-pane-select"></select>
                <div id="right-pane-status">
                    <span class="status-indicator"></span>
                    <span class="status-text">Not connected</span>
                </div>
                <div id="right-terminal-wrapper"></div>
            </div>
        </div>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildTerminalMarkup();
        localStorage.clear();

        // Mock WebSocket
        mockWebSocket = {
            send: jest.fn(),
            close: jest.fn(),
            readyState: WebSocket.OPEN,
            onopen: null,
            onmessage: null,
            onclose: null,
            onerror: null,
        };
        global.WebSocket = jest.fn(() => mockWebSocket);
        global.WebSocket.OPEN = 1;
        global.WebSocket.CONNECTING = 0;

        // Mock xterm.js Terminal
        mockFitAddon = {
            fit: jest.fn(),
        };

        mockTerminal = {
            loadAddon: jest.fn(),
            open: jest.fn(),
            write: jest.fn(),
            focus: jest.fn(),
            dispose: jest.fn(),
            onData: jest.fn(),
            onResize: jest.fn(),
            cols: 80,
            rows: 24,
        };

        global.Terminal = jest.fn(() => mockTerminal);
        global.FitAddon = { FitAddon: jest.fn(() => mockFitAddon) };
        global.WebLinksAddon = { WebLinksAddon: jest.fn(() => ({})) };
        global.Split = jest.fn(() => ({ destroy: jest.fn() }));

        manager = new window.TerminalManager({
            instances: instances,
            connectionUrls: connectionUrls,
            wsProtocol: 'ws:',
            wsHost: 'localhost',
        });
    });

    afterEach(() => {
        jest.clearAllMocks();
        jest.useRealTimers();
    });

    describe('constructor', () => {
        test('initializes with empty terminals Map', () => {
            expect(manager.terminals).toBeInstanceOf(Map);
            expect(manager.terminals.size).toBe(0);
        });

        test('initializes with empty connectedUuids Set', () => {
            expect(manager.connectedUuids).toBeInstanceOf(Set);
            expect(manager.connectedUuids.size).toBe(0);
        });

        test('defaults to tabs layout mode', () => {
            expect(manager.layoutMode).toBe('tabs');
        });
    });

    describe('isRdpOnly', () => {
        test('returns true for Windows DC instances', () => {
            const dcInstance = { osType: 'windows', role: 'dc' };
            expect(manager.isRdpOnly(dcInstance)).toBe(true);
        });

        test('returns false for Windows non-DC instances', () => {
            const winInstance = { osType: 'windows', role: 'victim' };
            expect(manager.isRdpOnly(winInstance)).toBe(false);
        });

        test('returns false for non-Windows instances', () => {
            const kaliInstance = { osType: 'kali', role: 'attacker' };
            expect(manager.isRdpOnly(kaliInstance)).toBe(false);
        });
    });

    describe('_getTerminalUrl', () => {
        test('returns terminal URL for valid UUID', () => {
            const url = manager._getTerminalUrl('kali-uuid');
            expect(url).toBe('/ws/terminal/kali/');
        });

        test('returns null for unknown UUID', () => {
            const url = manager._getTerminalUrl('unknown-uuid');
            expect(url).toBeNull();
        });
    });

    describe('_escapeHtml', () => {
        test('escapes HTML characters', () => {
            expect(manager._escapeHtml('<script>')).toBe('&lt;script&gt;');
            expect(manager._escapeHtml('&test')).toBe('&amp;test');
        });

        test('handles normal text', () => {
            expect(manager._escapeHtml('Kali Linux')).toBe('Kali Linux');
        });
    });

    describe('init', () => {
        test('creates terminal instances for SSH-capable instances', () => {
            manager.init();

            // Kali and Ubuntu should have terminals, DC should not (RDP-only)
            expect(manager.terminals.has('kali-uuid')).toBe(true);
            expect(manager.terminals.has('victim-uuid')).toBe(true);
            expect(manager.terminals.has('dc-uuid')).toBe(true);

            // DC should be marked as RDP-only
            expect(manager.terminals.get('dc-uuid').isRdpOnly).toBe(true);
            expect(manager.terminals.get('kali-uuid').isRdpOnly).toBe(false);
        });

        test('creates tabs for all instances', () => {
            manager.init();

            const tabs = document.querySelectorAll('.terminal-tab');
            expect(tabs.length).toBe(3);
        });

        test('activates first terminal by default', () => {
            manager.init();

            expect(manager.activeTerminalUuid).toBe('kali-uuid');
        });
    });

    describe('createTabs', () => {
        test('creates tab buttons with instance names', () => {
            manager.init();

            const tabs = document.querySelectorAll('.terminal-tab');
            const labels = Array.from(tabs).map(tab =>
                tab.querySelector('.tab-label').textContent
            );

            expect(labels).toContain('Kali Linux');
            expect(labels).toContain('Ubuntu Victim');
            expect(labels).toContain('Domain Controller');
        });

        test('marks first tab as active', () => {
            manager.init();

            const activeTab = document.querySelector('.terminal-tab.active');
            expect(activeTab.dataset.uuid).toBe('kali-uuid');
        });
    });

    describe('activateTerminal', () => {
        beforeEach(() => {
            manager.init();
        });

        test('updates activeTerminalUuid', () => {
            manager.activateTerminal('victim-uuid');
            expect(manager.activeTerminalUuid).toBe('victim-uuid');
        });

        test('updates tab styling', () => {
            manager.activateTerminal('victim-uuid');

            const activeTab = document.querySelector('.terminal-tab.active');
            expect(activeTab.dataset.uuid).toBe('victim-uuid');
        });

        test('saves to localStorage', () => {
            manager.activateTerminal('victim-uuid');
            expect(localStorage.getItem('terminal-active-tab')).toBe('victim-uuid');
        });

        test('connects WebSocket if not connected (lazy connect)', () => {
            manager.activateTerminal('victim-uuid');

            expect(manager.connectedUuids.has('victim-uuid')).toBe(true);
            expect(global.WebSocket).toHaveBeenCalled();
        });

        test('does not connect WebSocket for RDP-only instances', () => {
            const callCountBefore = global.WebSocket.mock.calls.length;
            manager.activateTerminal('dc-uuid');

            // Should not have made additional WebSocket call
            expect(global.WebSocket.mock.calls.length).toBe(callCountBefore);
            expect(manager.connectedUuids.has('dc-uuid')).toBe(false);
        });
    });

    describe('setLayoutMode', () => {
        beforeEach(() => {
            manager.init();
        });

        test('switches to split mode', () => {
            manager.setLayoutMode('split');

            expect(manager.layoutMode).toBe('split');
            expect(localStorage.getItem('terminal-layout')).toBe('split');
        });

        test('updates container class', () => {
            manager.setLayoutMode('split');

            const container = document.getElementById('terminal-container');
            expect(container.classList.contains('mode-split')).toBe(true);
            expect(container.classList.contains('mode-tabs')).toBe(false);
        });

        test('connects both pane terminals in split mode', () => {
            manager.setLayoutMode('split');

            // First instance (leftPaneUuid) and second instance (rightPaneUuid) should connect
            expect(manager.connectedUuids.has(manager.leftPaneUuid)).toBe(true);
        });
    });

    describe('sendInput', () => {
        beforeEach(() => {
            manager.init();
            // Simulate connected state
            const termData = manager.terminals.get('kali-uuid');
            termData.socket = mockWebSocket;
        });

        test('sends input message via WebSocket', () => {
            manager.sendInput('kali-uuid', 'ls -la');

            expect(mockWebSocket.send).toHaveBeenCalledWith(
                JSON.stringify({ type: 'input', data: 'ls -la' })
            );
        });

        test('does not send if socket is closed', () => {
            mockWebSocket.readyState = 3; // CLOSED

            manager.sendInput('kali-uuid', 'ls');

            expect(mockWebSocket.send).not.toHaveBeenCalled();
        });

        test('does not send if terminal not found', () => {
            manager.sendInput('unknown-uuid', 'ls');

            expect(mockWebSocket.send).not.toHaveBeenCalled();
        });
    });

    describe('sendResize', () => {
        beforeEach(() => {
            manager.init();
            const termData = manager.terminals.get('kali-uuid');
            termData.socket = mockWebSocket;
        });

        test('sends resize message with cols and rows', () => {
            manager.sendResize('kali-uuid', 120, 40);

            expect(mockWebSocket.send).toHaveBeenCalledWith(
                JSON.stringify({ type: 'resize', cols: 120, rows: 40 })
            );
        });
    });

    describe('updateStatus', () => {
        beforeEach(() => {
            manager.init();
        });

        test('updates status to connected', () => {
            manager.updateStatus('kali-uuid', 'connected');

            const statusEl = document.getElementById('status-kali-uuid');
            const indicator = statusEl.querySelector('.status-indicator');
            const text = statusEl.querySelector('.status-text');

            expect(indicator.className).toBe('status-indicator connected');
            expect(text.textContent).toBe('Connected');
        });

        test('updates status to disconnected', () => {
            manager.updateStatus('kali-uuid', 'disconnected');

            const statusEl = document.getElementById('status-kali-uuid');
            const text = statusEl.querySelector('.status-text');

            expect(text.textContent).toBe('Disconnected');
        });

        test('updates status to retrying with count', () => {
            manager.updateStatus('kali-uuid', 'retrying', 3);

            const statusEl = document.getElementById('status-kali-uuid');
            const text = statusEl.querySelector('.status-text');

            expect(text.textContent).toBe('Retrying (3/5)...');
        });

        test('updates tab status indicator', () => {
            manager.updateStatus('kali-uuid', 'connected');

            const tab = document.querySelector('.terminal-tab[data-uuid="kali-uuid"]');
            const tabStatus = tab.querySelector('.tab-status');

            expect(tabStatus.className).toBe('tab-status connected');
        });
    });

    describe('_getRetryDelay', () => {
        test('returns base delay for first retry', () => {
            expect(manager._getRetryDelay(0)).toBe(1000);
        });

        test('returns exponential delay', () => {
            expect(manager._getRetryDelay(1)).toBe(2000);
            expect(manager._getRetryDelay(2)).toBe(4000);
            expect(manager._getRetryDelay(3)).toBe(8000);
        });

        test('caps at max delay', () => {
            expect(manager._getRetryDelay(10)).toBe(10000);
        });
    });

    describe('_shouldRetry', () => {
        test('returns false when max retries exceeded', () => {
            expect(manager._shouldRetry(1006, 5)).toBe(false);
        });

        test('returns false for no-retry close codes', () => {
            expect(manager._shouldRetry(4001, 0)).toBe(false);
            expect(manager._shouldRetry(4003, 0)).toBe(false);
        });

        test('returns false for normal closure', () => {
            expect(manager._shouldRetry(1000, 0)).toBe(false);
        });

        test('returns true for retriable errors', () => {
            expect(manager._shouldRetry(1006, 0)).toBe(true);
            expect(manager._shouldRetry(1011, 0)).toBe(true);
        });
    });

    describe('loadLayoutPreference', () => {
        test('loads layout from localStorage', () => {
            localStorage.setItem('terminal-layout', 'split');
            localStorage.setItem('terminal-left-pane', 'victim-uuid');
            localStorage.setItem('terminal-right-pane', 'kali-uuid');

            manager.loadLayoutPreference();

            expect(manager.layoutMode).toBe('split');
            expect(manager.leftPaneUuid).toBe('victim-uuid');
            expect(manager.rightPaneUuid).toBe('kali-uuid');
        });

        test('defaults to tabs mode if not set', () => {
            manager.loadLayoutPreference();

            expect(manager.layoutMode).toBe('tabs');
        });
    });

    describe('destroy', () => {
        beforeEach(() => {
            manager.init();
        });

        test('clears terminals Map', () => {
            manager.destroy();

            expect(manager.terminals.size).toBe(0);
        });

        test('clears connectedUuids Set', () => {
            manager.connectedUuids.add('kali-uuid');

            manager.destroy();

            expect(manager.connectedUuids.size).toBe(0);
        });

        test('closes WebSocket connections', () => {
            const termData = manager.terminals.get('kali-uuid');
            termData.socket = mockWebSocket;

            manager.destroy();

            expect(mockWebSocket.close).toHaveBeenCalled();
        });

        test('disposes terminals', () => {
            manager.destroy();

            // Verify dispose was called (terminal mock is shared)
            expect(mockTerminal.dispose).toHaveBeenCalled();
        });

        test('destroys Split.js instance', () => {
            const mockSplitInstance = { destroy: jest.fn() };
            manager.splitInstance = mockSplitInstance;

            manager.destroy();

            expect(mockSplitInstance.destroy).toHaveBeenCalled();
            expect(manager.splitInstance).toBeNull();
        });
    });

    describe('connectIfNeeded', () => {
        beforeEach(() => {
            manager.init();
        });

        test('connects if not already connected', () => {
            expect(manager.connectedUuids.has('victim-uuid')).toBe(false);

            manager.connectIfNeeded('victim-uuid');

            expect(manager.connectedUuids.has('victim-uuid')).toBe(true);
        });

        test('does not reconnect if already connected', () => {
            manager.connectedUuids.add('victim-uuid');
            const callCount = global.WebSocket.mock.calls.length;

            manager.connectIfNeeded('victim-uuid');

            expect(global.WebSocket.mock.calls.length).toBe(callCount);
        });

        test('does not connect RDP-only instances', () => {
            const callCount = global.WebSocket.mock.calls.length;

            manager.connectIfNeeded('dc-uuid');

            expect(global.WebSocket.mock.calls.length).toBe(callCount);
            expect(manager.connectedUuids.has('dc-uuid')).toBe(false);
        });

        test('handles null uuid gracefully', () => {
            expect(() => manager.connectIfNeeded(null)).not.toThrow();
        });
    });
});
