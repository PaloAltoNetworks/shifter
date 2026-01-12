require('./terminal.js');

describe('TerminalManager', () => {
    let manager;
    let mockWebSocket;
    let mockTerminal;
    let mockFitAddon;

    const buildTerminalMarkup = () => `
        <div id="kali-terminal"></div>
        <div id="victim-terminal"></div>
        <div id="terminal-container">
            <div id="kali-pane" style="width: 50%;"></div>
            <div id="terminal-divider"></div>
            <div id="victim-pane" style="width: 50%;"></div>
        </div>
        <div id="kali-status">
            <span class="status-indicator"></span>
            <span>Connecting...</span>
        </div>
        <div id="victim-status">
            <span class="status-indicator"></span>
            <span>Connecting...</span>
        </div>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildTerminalMarkup();

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

        manager = new window.TerminalManager({
            instances: [
                { role: 'attacker', uuid: 'kali-uuid' },
                { role: 'victim', uuid: 'victim-uuid' },
            ],
            connectionUrls: [
                { uuid: 'kali-uuid', terminalUrl: '/ws/terminal/kali/' },
                { uuid: 'victim-uuid', terminalUrl: '/ws/terminal/victim/' },
            ],
            kaliContainerId: 'kali-terminal',
            victimContainerId: 'victim-terminal',
            wsProtocol: 'ws:',
            wsHost: 'localhost',
        });
    });

    afterEach(() => {
        jest.clearAllMocks();
        jest.useRealTimers();
    });

    describe('_getInstanceByRole', () => {
        test('returns attacker instance', () => {
            const instance = manager._getInstanceByRole('attacker');
            expect(instance.uuid).toBe('kali-uuid');
        });

        test('returns victim instance', () => {
            const instance = manager._getInstanceByRole('victim');
            expect(instance.uuid).toBe('victim-uuid');
        });

        test('returns undefined for unknown role', () => {
            const instance = manager._getInstanceByRole('unknown');
            expect(instance).toBeUndefined();
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

    describe('sendInput', () => {
        test('sends input message to kali socket', () => {
            manager.kaliSocket = mockWebSocket;

            manager.sendInput('kali', 'ls -la');

            expect(mockWebSocket.send).toHaveBeenCalledWith(
                JSON.stringify({ type: 'input', data: 'ls -la' })
            );
        });

        test('sends input message to victim socket', () => {
            manager.victimSocket = mockWebSocket;

            manager.sendInput('victim', 'whoami');

            expect(mockWebSocket.send).toHaveBeenCalledWith(
                JSON.stringify({ type: 'input', data: 'whoami' })
            );
        });

        test('does not send if socket is closed', () => {
            mockWebSocket.readyState = 3; // CLOSED
            manager.kaliSocket = mockWebSocket;

            manager.sendInput('kali', 'ls');

            expect(mockWebSocket.send).not.toHaveBeenCalled();
        });
    });

    describe('sendResize', () => {
        test('sends resize message with cols and rows', () => {
            manager.kaliSocket = mockWebSocket;

            manager.sendResize('kali', 120, 40);

            expect(mockWebSocket.send).toHaveBeenCalledWith(
                JSON.stringify({ type: 'resize', cols: 120, rows: 40 })
            );
        });
    });

    describe('updateStatus', () => {
        test('updates status to connected', () => {
            manager.updateStatus('kali', 'connected');

            const statusEl = document.getElementById('kali-status');
            const indicator = statusEl.querySelector('.status-indicator');
            const text = statusEl.querySelector('span:last-child');

            expect(indicator.className).toBe('status-indicator connected');
            expect(text.textContent).toBe('Connected');
        });

        test('updates status to disconnected', () => {
            manager.updateStatus('kali', 'disconnected');

            const statusEl = document.getElementById('kali-status');
            const text = statusEl.querySelector('span:last-child');

            expect(text.textContent).toBe('Disconnected');
        });

        test('updates status to retrying with count', () => {
            manager.updateStatus('kali', 'retrying', 3);

            const statusEl = document.getElementById('kali-status');
            const text = statusEl.querySelector('span:last-child');

            expect(text.textContent).toBe('Retrying (3/5)...');
        });

        test('resets retry counter on connected', () => {
            manager.kaliRetries = 3;
            manager.updateStatus('kali', 'connected');

            expect(manager.kaliRetries).toBe(0);
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

    describe('_scheduleRetry', () => {
        beforeEach(() => {
            jest.useFakeTimers();
            manager.kaliTerminal = mockTerminal;
            manager.victimTerminal = mockTerminal;
        });

        test('schedules retry and returns true for retriable error', () => {
            const result = manager._scheduleRetry('kali', 1006);

            expect(result).toBe(true);
            expect(mockTerminal.write).toHaveBeenCalledWith(
                expect.stringContaining('Retrying in 1s')
            );
        });

        test('returns false for non-retriable error', () => {
            const result = manager._scheduleRetry('kali', 4001);

            expect(result).toBe(false);
        });

        test('increments retry counter after delay', () => {
            manager.connectKali = jest.fn();
            manager._scheduleRetry('kali', 1006);

            jest.advanceTimersByTime(1000);

            expect(manager.kaliRetries).toBe(1);
            expect(manager.connectKali).toHaveBeenCalled();
        });
    });

    describe('destroy', () => {
        test('clears retry timeouts', () => {
            jest.useFakeTimers();
            manager.kaliRetryTimeout = setTimeout(() => {}, 1000);
            manager.victimRetryTimeout = setTimeout(() => {}, 1000);

            manager.destroy();

            // Timeouts should be cleared (no error when advancing timers)
            expect(() => jest.advanceTimersByTime(2000)).not.toThrow();
        });

        test('closes WebSocket connections', () => {
            manager.kaliSocket = mockWebSocket;
            manager.victimSocket = { ...mockWebSocket, close: jest.fn() };

            manager.destroy();

            expect(mockWebSocket.close).toHaveBeenCalled();
            expect(manager.victimSocket.close).toHaveBeenCalled();
        });

        test('disposes terminals', () => {
            manager.kaliTerminal = mockTerminal;
            manager.victimTerminal = { ...mockTerminal, dispose: jest.fn() };

            manager.destroy();

            expect(mockTerminal.dispose).toHaveBeenCalled();
            expect(manager.victimTerminal.dispose).toHaveBeenCalled();
        });
    });

    describe('divider resize', () => {
        test('setupDividerResize sets up mousedown handler', () => {
            manager.setupDividerResize();

            const divider = document.getElementById('terminal-divider');
            divider.dispatchEvent(new MouseEvent('mousedown', { clientX: 500 }));

            expect(manager.isDragging).toBe(true);
            expect(manager.startX).toBe(500);
        });

        test('mouseup ends dragging', () => {
            manager.setupDividerResize();
            manager.isDragging = true;

            document.dispatchEvent(new MouseEvent('mouseup'));

            expect(manager.isDragging).toBe(false);
        });
    });
});
