/**
 * Terminal Manager - Handles dual SSH terminal connections via WebSocket
 *
 * Uses xterm.js for terminal rendering and WebSocket for SSH communication.
 */

class TerminalManager {
    constructor(options) {
        this.rangeId = options.rangeId;
        this.kaliContainerId = options.kaliContainerId;
        this.victimContainerId = options.victimContainerId;
        this.wsProtocol = options.wsProtocol || 'ws:';
        this.wsHost = options.wsHost || window.location.host;

        // Terminal instances
        this.kaliTerminal = null;
        this.victimTerminal = null;

        // WebSocket connections
        this.kaliSocket = null;
        this.victimSocket = null;

        // Fit addons
        this.kaliFitAddon = null;
        this.victimFitAddon = null;

        // Divider state
        this.isDragging = false;
        this.startX = 0;
        this.startLeftWidth = 0;
    }

    /**
     * Initialize both terminals
     */
    init() {
        this.createTerminals();
        this.setupDividerResize();
        this.setupWindowResize();
        this.connectWebSockets();
    }

    /**
     * Create xterm.js terminal instances
     */
    createTerminals() {
        const terminalOptions = {
            theme: {
                background: '#0d0d0d',
                foreground: '#eaebeb',
                cursor: '#128df3',
                cursorAccent: '#0d0d0d',
                selectionBackground: 'rgba(18, 141, 243, 0.3)',
                black: '#000000',
                red: '#ff5555',
                green: '#50fa7b',
                yellow: '#f1fa8c',
                blue: '#128df3',
                magenta: '#ff79c6',
                cyan: '#8be9fd',
                white: '#eaebeb',
                brightBlack: '#666666',
                brightRed: '#ff6e6e',
                brightGreen: '#69ff94',
                brightYellow: '#ffffa5',
                brightBlue: '#6eb6ff',
                brightMagenta: '#ff92df',
                brightCyan: '#a4ffff',
                brightWhite: '#ffffff',
            },
            fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace",
            fontSize: 13,
            lineHeight: 1.2,
            cursorBlink: true,
            cursorStyle: 'block',
            scrollback: 5000,
            allowProposedApi: true,
        };

        // Create Kali terminal
        this.kaliTerminal = new Terminal(terminalOptions);
        this.kaliFitAddon = new FitAddon.FitAddon();
        const kaliWebLinksAddon = new WebLinksAddon.WebLinksAddon();
        this.kaliTerminal.loadAddon(this.kaliFitAddon);
        this.kaliTerminal.loadAddon(kaliWebLinksAddon);

        const kaliContainer = document.getElementById(this.kaliContainerId);
        this.kaliTerminal.open(kaliContainer);
        this.kaliFitAddon.fit();

        // Create Victim terminal
        this.victimTerminal = new Terminal(terminalOptions);
        this.victimFitAddon = new FitAddon.FitAddon();
        const victimWebLinksAddon = new WebLinksAddon.WebLinksAddon();
        this.victimTerminal.loadAddon(this.victimFitAddon);
        this.victimTerminal.loadAddon(victimWebLinksAddon);

        const victimContainer = document.getElementById(this.victimContainerId);
        this.victimTerminal.open(victimContainer);
        this.victimFitAddon.fit();

        // Setup input handlers
        this.kaliTerminal.onData((data) => this.sendInput('kali', data));
        this.victimTerminal.onData((data) => this.sendInput('victim', data));

        // Setup resize handlers
        this.kaliTerminal.onResize(({ cols, rows }) => this.sendResize('kali', cols, rows));
        this.victimTerminal.onResize(({ cols, rows }) => this.sendResize('victim', cols, rows));
    }

    /**
     * Connect WebSockets for both terminals
     */
    connectWebSockets() {
        this.connectKali();
        this.connectVictim();
    }

    /**
     * Connect Kali WebSocket
     */
    connectKali() {
        const url = `${this.wsProtocol}//${this.wsHost}/ws/terminal/${this.rangeId}/kali/`;
        this.kaliSocket = new WebSocket(url);

        this.kaliSocket.onopen = () => {
            this.updateStatus('kali', 'connected');
            this.kaliTerminal.focus();
            // Send initial size
            const { cols, rows } = this.kaliTerminal;
            this.sendResize('kali', cols, rows);
        };

        this.kaliSocket.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'output') {
                this.kaliTerminal.write(message.data);
            }
        };

        this.kaliSocket.onclose = (event) => {
            this.updateStatus('kali', 'disconnected');
            this.kaliTerminal.write('\r\n\x1b[31mConnection closed.\x1b[0m\r\n');
        };

        this.kaliSocket.onerror = (error) => {
            this.updateStatus('kali', 'disconnected');
            console.error('Kali WebSocket error:', error);
        };
    }

    /**
     * Connect Victim WebSocket
     */
    connectVictim() {
        const url = `${this.wsProtocol}//${this.wsHost}/ws/terminal/${this.rangeId}/victim/`;
        this.victimSocket = new WebSocket(url);

        this.victimSocket.onopen = () => {
            this.updateStatus('victim', 'connected');
            // Send initial size
            const { cols, rows } = this.victimTerminal;
            this.sendResize('victim', cols, rows);
        };

        this.victimSocket.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'output') {
                this.victimTerminal.write(message.data);
            }
        };

        this.victimSocket.onclose = (event) => {
            this.updateStatus('victim', 'disconnected');
            this.victimTerminal.write('\r\n\x1b[31mConnection closed.\x1b[0m\r\n');
        };

        this.victimSocket.onerror = (error) => {
            this.updateStatus('victim', 'disconnected');
            console.error('Victim WebSocket error:', error);
        };
    }

    /**
     * Send terminal input to WebSocket
     */
    sendInput(instance, data) {
        const socket = instance === 'kali' ? this.kaliSocket : this.victimSocket;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'input', data: data }));
        }
    }

    /**
     * Send terminal resize to WebSocket
     */
    sendResize(instance, cols, rows) {
        const socket = instance === 'kali' ? this.kaliSocket : this.victimSocket;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'resize', cols: cols, rows: rows }));
        }
    }

    /**
     * Update connection status indicator
     */
    updateStatus(instance, status) {
        const statusEl = document.getElementById(`${instance}-status`);
        if (!statusEl) return;

        const indicator = statusEl.querySelector('.status-indicator');
        const text = statusEl.querySelector('span:last-child');

        indicator.className = 'status-indicator ' + status;

        switch (status) {
            case 'connecting':
                text.textContent = 'Connecting...';
                break;
            case 'connected':
                text.textContent = 'Connected';
                break;
            case 'disconnected':
                text.textContent = 'Disconnected';
                break;
        }
    }

    /**
     * Setup divider drag-to-resize
     */
    setupDividerResize() {
        const divider = document.getElementById('terminal-divider');
        const container = document.getElementById('terminal-container');
        const kaliPane = document.getElementById('kali-pane');
        const victimPane = document.getElementById('victim-pane');

        if (!divider || !container) return;

        divider.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.startX = e.clientX;
            this.startLeftWidth = kaliPane.offsetWidth;

            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return;

            const containerWidth = container.offsetWidth;
            const dividerWidth = divider.offsetWidth;
            const minWidth = 300;
            const maxWidth = containerWidth - minWidth - dividerWidth;

            let newLeftWidth = this.startLeftWidth + (e.clientX - this.startX);
            newLeftWidth = Math.max(minWidth, Math.min(maxWidth, newLeftWidth));

            const leftPercent = (newLeftWidth / containerWidth) * 100;
            const rightPercent = ((containerWidth - newLeftWidth - dividerWidth) / containerWidth) * 100;

            kaliPane.style.flex = `0 0 ${leftPercent}%`;
            victimPane.style.flex = `0 0 ${rightPercent}%`;

            // Refit terminals
            this.kaliFitAddon.fit();
            this.victimFitAddon.fit();
        });

        document.addEventListener('mouseup', () => {
            if (this.isDragging) {
                this.isDragging = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }

    /**
     * Setup window resize handler
     */
    setupWindowResize() {
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                this.kaliFitAddon.fit();
                this.victimFitAddon.fit();
            }, 100);
        });
    }

    /**
     * Cleanup - close connections
     */
    destroy() {
        if (this.kaliSocket) {
            this.kaliSocket.close();
        }
        if (this.victimSocket) {
            this.victimSocket.close();
        }
        if (this.kaliTerminal) {
            this.kaliTerminal.dispose();
        }
        if (this.victimTerminal) {
            this.victimTerminal.dispose();
        }
    }
}

// Export for use in template
window.TerminalManager = TerminalManager;
