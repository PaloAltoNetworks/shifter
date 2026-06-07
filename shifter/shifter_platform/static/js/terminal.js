/**
 * Terminal Manager - Handles N SSH terminal connections via WebSocket
 *
 * Supports tabbed and split view layouts with lazy WebSocket connections.
 * Uses xterm.js for terminal rendering and WebSocket for SSH communication.
 */
// TerminalLayoutBase and the shared status constants are published on
// globalThis by terminal-layout.js, which must load before this script.
const TerminalLayoutBase = globalThis.TerminalLayoutBase;
const STATUS_INDICATOR_CLASS = globalThis.STATUS_INDICATOR_CLASS;
const NOT_CONNECTED_TEXT = globalThis.NOT_CONNECTED_TEXT;

class TerminalManager extends TerminalLayoutBase {
    constructor(options) {
        super();
        this.instances = options.instances || [];
        this.connectionUrls = options.connectionUrls || [];
        this.wsProtocol = options.wsProtocol || 'ws:';
        this.wsHost = options.wsHost || globalThis.location.host;

        // Terminal storage: Map<uuid, {terminal, fitAddon, socket, retries, retryTimeout}>
        this.terminals = new Map();

        // Lazy connection tracking
        this.connectedUuids = new Set();

        // Layout state
        this.layoutMode = 'tabs';  // 'tabs' or 'split'
        this.activeTerminalUuid = null;

        // Split mode state
        this.leftPaneUuid = null;
        this.rightPaneUuid = null;
        this.splitInstance = null;

        // Retry configuration
        this.retryConfig = {
            maxRetries: 5,
            baseDelayMs: 1000,
            maxDelayMs: 10000,
            noRetryCodes: [4001, 4003],
        };

        // Terminal options
        this.terminalOptions = {
            theme: {
                background: '#0d0d0d',
                foreground: '#eaebeb',
                cursor: '#94a3b8',
                cursorAccent: '#0d0d0d',
                selectionBackground: 'rgba(148, 163, 184, 0.3)',
                black: '#000000',
                red: '#ff5555',
                green: '#50fa7b',
                yellow: '#f1fa8c',
                blue: '#5391e6',
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
    }

    /**
     * Initialize the terminal manager
     */
    init() {
        console.log(`TerminalManager: Initializing with ${this.instances.length} instances`);
        this.loadLayoutPreference();
        this.createTerminalInstances();
        this.createTabs();
        this.createPaneDropdowns();
        this.setupLayoutToggle();
        this.setupWindowResize();
        this.applyLayoutMode();

        if (this.instances.length > 0) {
            if (this.layoutMode === 'split') {
                // In split mode, connect both panes and set up split view
                this.connectIfNeeded(this.leftPaneUuid);
                this.connectIfNeeded(this.rightPaneUuid);
                this.mountSplitPaneTerminals();
                this.initSplitJs();
            } else {
                // In tabs mode, activate and connect the active terminal
                this.activateTerminal(this.activeTerminalUuid || this.instances[0].uuid);
            }
        }
        console.log(`TerminalManager: Initialized in ${this.layoutMode} mode`);
    }

    /**
     * Load layout preference from localStorage
     * Validates that stored UUIDs exist in current instances (handles range changes)
     */
    loadLayoutPreference() {
        this.layoutMode = localStorage.getItem('terminal-layout') || 'tabs';

        // Get valid UUIDs from current instances
        const validUuids = new Set(this.instances.map(i => i.uuid));

        // Validate stored UUIDs - fall back to current instances if stale
        const storedLeftPane = localStorage.getItem('terminal-left-pane');
        const storedRightPane = localStorage.getItem('terminal-right-pane');
        const storedActiveTab = localStorage.getItem('terminal-active-tab');

        this.leftPaneUuid = (storedLeftPane && validUuids.has(storedLeftPane))
            ? storedLeftPane
            : this.instances[0]?.uuid;
        this.rightPaneUuid = (storedRightPane && validUuids.has(storedRightPane))
            ? storedRightPane
            : this.instances[1]?.uuid || this.instances[0]?.uuid;
        this.activeTerminalUuid = (storedActiveTab && validUuids.has(storedActiveTab))
            ? storedActiveTab
            : this.instances[0]?.uuid;
    }

    /**
     * Check if an instance is RDP-only (no SSH access)
     */
    isRdpOnly(_instance) {
        // All instances support SSH - no RDP-only instances
        return false;
    }

    /**
     * Create xterm.js terminal instances for all instances (but don't connect yet)
     */
    createTerminalInstances() {
        this.instances.forEach(instance => {
            const containerId = `terminal-${instance.uuid}`;
            const container = document.getElementById(containerId);

            if (!container) {
                console.warn(`TerminalManager: Container not found: ${containerId}`);
                return;
            }

            // Check if this is an RDP-only instance
            if (this.isRdpOnly(instance)) {
                this.createRdpOnlyPlaceholder(instance, container);
                return;
            }

            // Create terminal instance
            const terminal = new Terminal(this.terminalOptions);
            const fitAddon = new FitAddon.FitAddon();
            const webLinksAddon = new WebLinksAddon.WebLinksAddon();

            terminal.loadAddon(fitAddon);
            terminal.loadAddon(webLinksAddon);
            terminal.open(container);

            // Wire clipboard: Ctrl+Shift+C copies selection, Ctrl+Shift+V pastes.
            // Without this xterm.js shows highlighting but never reaches the
            // system clipboard, so participants can't copy command output.
            terminal.attachCustomKeyEventHandler((ev) => {
                if (ev.type !== 'keydown') return true;
                if (ev.ctrlKey && ev.shiftKey && (ev.key === 'C' || ev.key === 'c')) {
                    const sel = terminal.getSelection();
                    if (sel) {
                        navigator.clipboard.writeText(sel).catch(() => {});
                    }
                    return false;
                }
                if (ev.ctrlKey && ev.shiftKey && (ev.key === 'V' || ev.key === 'v')) {
                    navigator.clipboard.readText().then((txt) => {
                        if (txt) this.sendInput(instance.uuid, txt);
                    }).catch(() => {});
                    return false;
                }
                return true;
            });

            // Store terminal data
            this.terminals.set(instance.uuid, {
                terminal,
                fitAddon,
                socket: null,
                retries: 0,
                retryTimeout: null,
                instance,
                isRdpOnly: false,
            });

            // Setup input handler (will queue if not connected)
            terminal.onData((data) => this.sendInput(instance.uuid, data));
            terminal.onResize(({ cols, rows }) => this.sendResize(instance.uuid, cols, rows));
        });
    }

    /**
     * Create RDP-only placeholder for instances without SSH access
     */
    createRdpOnlyPlaceholder(instance, container) {
        // Clear container and add placeholder
        container.innerHTML = `
            <div class="rdp-only-message">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style="opacity: 0.5;">
                    <rect x="2" y="3" width="20" height="14" rx="2" stroke="currentColor" stroke-width="2"/>
                    <path d="M8 21H16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    <path d="M12 17V21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
                <p>This instance is accessible via RDP only.</p>
                <button class="pane-action-btn rdp-btn" data-uuid="${instance.uuid}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <rect x="2" y="3" width="20" height="14" rx="2" stroke="currentColor" stroke-width="2"/>
                        <path d="M8 21H16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                        <path d="M12 17V21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <span>Open RDP Session</span>
                </button>
            </div>
        `;

        // Store minimal data for RDP-only instances
        this.terminals.set(instance.uuid, {
            terminal: null,
            fitAddon: null,
            socket: null,
            retries: 0,
            retryTimeout: null,
            instance,
            isRdpOnly: true,
        });
    }


    /**
     * Connect WebSocket if not already connected
     */
    connectIfNeeded(uuid) {
        if (!uuid || this.connectedUuids.has(uuid)) return;

        // Skip RDP-only instances
        const termData = this.terminals.get(uuid);
        if (termData?.isRdpOnly) return;

        this.connectWebSocket(uuid);
        this.connectedUuids.add(uuid);
    }

    /**
     * Get terminal URL for an instance UUID
     */
    _getTerminalUrl(uuid) {
        const conn = this.connectionUrls.find(c => c.uuid === uuid);
        return conn ? conn.terminalUrl : null;
    }

    /**
     * Connect WebSocket for a terminal
     */
    connectWebSocket(uuid) {
        const termData = this.terminals.get(uuid);
        if (!termData) return;

        const terminalUrl = this._getTerminalUrl(uuid);
        if (!terminalUrl) {
            console.error(`TerminalManager: No terminal URL found for instance ${uuid}`);
            this.updateStatus(uuid, 'failed');
            return;
        }

        this.updateStatus(uuid, 'connecting');

        const url = `${this.wsProtocol}//${this.wsHost}${terminalUrl}`;
        console.log(`TerminalManager: Connecting WebSocket to ${url}`);
        const socket = new WebSocket(url);

        socket.onopen = () => {
            console.log(`TerminalManager: WebSocket connected for ${termData.instance?.name || uuid}`);
            this.updateStatus(uuid, 'connected');
            termData.retries = 0;
            termData.fitAddon.fit();

            // Send initial size
            const { cols, rows } = termData.terminal;
            this.sendResize(uuid, cols, rows);

            // Focus if this is the active terminal
            if (uuid === this.activeTerminalUuid && this.layoutMode === 'tabs') {
                termData.terminal.focus();
            }
        };

        socket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                if (message.type === 'output') {
                    termData.terminal.write(message.data);
                }
            } catch (e) {
                console.error('TerminalManager: Failed to parse WebSocket message:', e);
            }
        };

        socket.onclose = (event) => {
            if (!this._scheduleRetry(uuid, event.code)) {
                this.updateStatus(uuid, 'disconnected');
                termData.terminal.write('\r\n\x1b[31mConnection closed.\x1b[0m\r\n');
            }
        };

        socket.onerror = (error) => {
            console.error(`TerminalManager: WebSocket error for ${termData.instance?.name || uuid}:`, error);
        };

        termData.socket = socket;
    }

    /**
     * Send terminal input to WebSocket
     */
    sendInput(uuid, data) {
        const termData = this.terminals.get(uuid);
        if (termData?.socket?.readyState === WebSocket.OPEN) {
            termData.socket.send(JSON.stringify({ type: 'input', data }));
        }
    }

    /**
     * Send terminal resize to WebSocket
     */
    sendResize(uuid, cols, rows) {
        const termData = this.terminals.get(uuid);
        if (termData?.socket?.readyState === WebSocket.OPEN) {
            termData.socket.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
    }

    /**
     * Update connection status indicator
     */
    updateStatus(uuid, status, retryCount = null) {
        // Update pane status (tab mode)
        const statusEl = document.getElementById(`status-${uuid}`);
        if (statusEl) {
            const indicator = statusEl.querySelector('.status-indicator');
            const text = statusEl.querySelector('.status-text');

            if (indicator) {
                indicator.className = STATUS_INDICATOR_CLASS + ' ' + status;
            }

            if (text) {
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
                    case 'retrying':
                        text.textContent = `Retrying (${retryCount}/${this.retryConfig.maxRetries})...`;
                        break;
                    case 'failed':
                        text.textContent = 'Failed';
                        break;
                    default:
                        text.textContent = NOT_CONNECTED_TEXT;
                }
            }
        }

        // Update tab status
        const tab = document.querySelector(`.terminal-tab[data-uuid="${uuid}"]`);
        if (tab) {
            const tabStatus = tab.querySelector('.tab-status');
            if (tabStatus) {
                tabStatus.className = 'tab-status ' + status;
            }
        }

        // Update split pane status if applicable
        if (uuid === this.leftPaneUuid) {
            this.updateSplitPaneStatus('left', uuid);
        }
        if (uuid === this.rightPaneUuid) {
            this.updateSplitPaneStatus('right', uuid);
        }
    }

    /**
     * Calculate retry delay with exponential backoff
     */
    _getRetryDelay(retryCount) {
        return Math.min(
            this.retryConfig.baseDelayMs * Math.pow(2, retryCount),
            this.retryConfig.maxDelayMs
        );
    }

    /**
     * Check if we should retry based on close code
     */
    _shouldRetry(closeCode, retryCount) {
        if (retryCount >= this.retryConfig.maxRetries) return false;
        if (this.retryConfig.noRetryCodes.includes(closeCode)) return false;
        if (closeCode === 1000) return false;
        return true;
    }

    /**
     * Schedule a retry for the given instance
     */
    _scheduleRetry(uuid, closeCode) {
        const termData = this.terminals.get(uuid);
        if (!termData) return false;

        if (!this._shouldRetry(closeCode, termData.retries)) {
            this.updateStatus(uuid, 'failed');
            if (termData.retries >= this.retryConfig.maxRetries) {
                termData.terminal.write('\r\n\x1b[31mConnection failed after 5 attempts. Refresh page to retry.\x1b[0m\r\n');
            }
            return false;
        }

        const delay = this._getRetryDelay(termData.retries);
        this.updateStatus(uuid, 'retrying', termData.retries + 1);

        termData.terminal.write(`\r\n\x1b[33mRetrying in ${delay/1000}s... (attempt ${termData.retries + 1}/${this.retryConfig.maxRetries})\x1b[0m\r\n`);

        termData.retryTimeout = setTimeout(() => {
            termData.retries++;
            this.connectWebSocket(uuid);
        }, delay);

        return true;
    }

    /**
     * Setup globalThis resize handler
     */
    setupWindowResize() {
        let resizeTimeout;
        globalThis.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                this.fitVisibleTerminals();
            }, 100);
        });
    }

    /**
     * Fit all visible terminals
     */
    fitVisibleTerminals() {
        if (this.layoutMode === 'tabs') {
            // Fit only active terminal (if it has one - skip RDP-only)
            const termData = this.terminals.get(this.activeTerminalUuid);
            if (termData && termData.fitAddon) {
                termData.fitAddon.fit();
            }
        } else {
            // Fit both split pane terminals (skip RDP-only)
            [this.leftPaneUuid, this.rightPaneUuid].forEach(uuid => {
                const termData = this.terminals.get(uuid);
                if (termData && termData.fitAddon) {
                    termData.fitAddon.fit();
                }
            });
        }
    }

    /**
     * Escape HTML to prevent XSS
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Cleanup - close connections and clear retry timeouts
     */
    destroy() {
        // Destroy Split.js instance
        if (this.splitInstance) {
            this.splitInstance.destroy();
            this.splitInstance = null;
        }

        // Clean up all terminals
        this.terminals.forEach((termData, _uuid) => {
            if (termData.retryTimeout) {
                clearTimeout(termData.retryTimeout);
            }
            if (termData.socket) {
                termData.socket.close();
            }
            if (termData.terminal) {
                termData.terminal.dispose();
            }
        });

        this.terminals.clear();
        this.connectedUuids.clear();
    }
}

// Export for use in template
globalThis.TerminalManager = TerminalManager;
