/**
 * Terminal Manager - Handles N SSH terminal connections via WebSocket
 *
 * Supports tabbed and split view layouts with lazy WebSocket connections.
 * Uses xterm.js for terminal rendering and WebSocket for SSH communication.
 */
/* global Split */

class TerminalManager {
    constructor(options) {
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
     * Create tab buttons in the tab bar
     */
    createTabs() {
        const tabsContainer = document.getElementById('terminal-tabs');
        if (!tabsContainer) return;

        tabsContainer.innerHTML = '';

        this.instances.forEach(instance => {
            const tab = document.createElement('button');
            tab.className = 'terminal-tab';
            tab.dataset.uuid = instance.uuid;

            if (instance.uuid === this.activeTerminalUuid) {
                tab.classList.add('active');
            }

            tab.innerHTML = `
                <span class="tab-status"></span>
                <span class="tab-label">${this._escapeHtml(instance.name)}</span>
            `;

            tab.addEventListener('click', () => this.activateTerminal(instance.uuid));
            tabsContainer.appendChild(tab);
        });
    }

    /**
     * Populate pane dropdown selectors for split mode
     */
    createPaneDropdowns() {
        ['left', 'right'].forEach(side => {
            const dropdown = document.getElementById(`${side}-pane-select`);
            if (!dropdown) return;

            dropdown.innerHTML = '';

            this.instances.forEach(instance => {
                const option = document.createElement('option');
                option.value = instance.uuid;
                option.textContent = instance.name;
                dropdown.appendChild(option);
            });

            // Set initial value
            const initialUuid = side === 'left' ? this.leftPaneUuid : this.rightPaneUuid;
            if (initialUuid) {
                dropdown.value = initialUuid;
            }

            dropdown.addEventListener('change', (e) => this.onPaneSelectChange(side, e.target.value));
        });
    }

    /**
     * Setup layout toggle button handlers
     */
    setupLayoutToggle() {
        const toggleContainer = document.getElementById('layout-toggle');
        if (!toggleContainer) return;

        toggleContainer.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                if (mode && mode !== this.layoutMode) {
                    this.setLayoutMode(mode);
                }
            });
        });

        // Set initial active state
        this.updateToggleButtons();
    }

    /**
     * Update toggle button active states
     */
    updateToggleButtons() {
        const toggleContainer = document.getElementById('layout-toggle');
        if (!toggleContainer) return;

        toggleContainer.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === this.layoutMode);
        });
    }

    /**
     * Set layout mode and apply changes
     */
    setLayoutMode(mode) {
        console.log(`TerminalManager: Switching to ${mode} mode`);
        this.layoutMode = mode;
        localStorage.setItem('terminal-layout', mode);

        this.applyLayoutMode();
        this.updateToggleButtons();

        if (mode === 'split') {
            // In split mode, ensure both pane terminals are connected
            this.connectIfNeeded(this.leftPaneUuid);
            this.connectIfNeeded(this.rightPaneUuid);
            this.mountSplitPaneTerminals();
            this.initSplitJs();
        } else {
            // Switching to tabs mode - destroy split instance and restore terminals
            this.restoreTerminalsToTabPanes();
            // Activate the current active terminal (connect if needed, show and fit)
            this.activateTerminal(this.activeTerminalUuid || this.instances[0]?.uuid);
        }

        // Refit visible terminals after layout change
        setTimeout(() => this.fitVisibleTerminals(), 50);
    }

    /**
     * Restore terminals from split panes back to their tab pane containers
     */
    restoreTerminalsToTabPanes() {
        // Destroy Split.js instance
        if (this.splitInstance) {
            this.splitInstance.destroy();
            this.splitInstance = null;
        }

        // Move xterm elements back from split pane wrappers to their original containers
        [this.leftPaneUuid, this.rightPaneUuid].forEach((uuid, index) => {
            const side = index === 0 ? 'left' : 'right';
            const wrapper = document.getElementById(`${side}-terminal-wrapper`);
            if (!wrapper) return;

            const xtermElement = wrapper.querySelector('.xterm');
            if (!xtermElement) return;

            // Find the original tab container for this terminal
            const tabContainer = document.getElementById(`terminal-${uuid}`);
            if (tabContainer && !tabContainer.querySelector('.xterm')) {
                tabContainer.appendChild(xtermElement);
            }
        });

        // Clear split pane wrappers
        ['left-terminal-wrapper', 'right-terminal-wrapper'].forEach(id => {
            const wrapper = document.getElementById(id);
            if (wrapper) wrapper.innerHTML = '';
        });
    }

    /**
     * Apply CSS classes for current layout mode
     */
    applyLayoutMode() {
        const container = document.getElementById('terminal-container');
        if (!container) return;

        container.classList.remove('mode-tabs', 'mode-split');
        container.classList.add(`mode-${this.layoutMode}`);

        // Show/hide tabs bar
        const tabsBar = document.getElementById('terminal-tabs');
        if (tabsBar) {
            tabsBar.style.display = this.layoutMode === 'tabs' ? 'flex' : 'none';
        }
    }

    /**
     * Activate a terminal (tab mode) - show it and connect if needed
     */
    activateTerminal(uuid) {
        if (!uuid || !this.terminals.has(uuid)) return;

        const instance = this.instances.find(i => i.uuid === uuid);
        console.log(`TerminalManager: Activating terminal ${instance?.name || uuid}`);

        this.activeTerminalUuid = uuid;
        localStorage.setItem('terminal-active-tab', uuid);

        // Update tab styling
        document.querySelectorAll('.terminal-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.uuid === uuid);
        });

        // Update pane visibility (tab mode)
        document.querySelectorAll('.terminal-pane').forEach(pane => {
            pane.classList.toggle('active', pane.dataset.uuid === uuid);
        });

        // Lazy connect (unless RDP-only)
        this.connectIfNeeded(uuid);

        // Fit and focus (only if it has a terminal)
        const termData = this.terminals.get(uuid);
        if (termData && termData.terminal && termData.fitAddon) {
            setTimeout(() => {
                termData.fitAddon.fit();
                termData.terminal.focus();
            }, 50);
        }
    }

    /**
     * Handle pane dropdown selection change (split mode)
     */
    onPaneSelectChange(side, uuid) {
        if (side === 'left') {
            this.leftPaneUuid = uuid;
            localStorage.setItem('terminal-left-pane', uuid);
        } else {
            this.rightPaneUuid = uuid;
            localStorage.setItem('terminal-right-pane', uuid);
        }

        // Lazy connect
        this.connectIfNeeded(uuid);

        // Mount terminal to pane
        this.mountTerminalToSplitPane(side, uuid);

        // Fit terminals
        setTimeout(() => this.fitVisibleTerminals(), 50);
    }

    /**
     * Mount terminals to split panes
     */
    mountSplitPaneTerminals() {
        this.mountTerminalToSplitPane('left', this.leftPaneUuid);
        this.mountTerminalToSplitPane('right', this.rightPaneUuid);
    }

    /**
     * Mount a terminal to a split pane
     */
    mountTerminalToSplitPane(side, uuid) {
        const wrapper = document.getElementById(`${side}-terminal-wrapper`);
        if (!wrapper) return;

        // Clear existing content
        wrapper.innerHTML = '';

        const termData = this.terminals.get(uuid);
        if (!termData) return;

        // Get the terminal's container element
        const terminalContainer = document.getElementById(`terminal-${uuid}`);
        if (terminalContainer) {
            if (termData.isRdpOnly) {
                // For RDP-only, copy the placeholder content
                const rdpMessage = terminalContainer.querySelector('.rdp-only-message');
                if (rdpMessage) {
                    wrapper.appendChild(rdpMessage.cloneNode(true));
                }
            } else {
                // For regular terminals, move the xterm element
                const xtermElement = terminalContainer.querySelector('.xterm');
                if (xtermElement) {
                    wrapper.appendChild(xtermElement);
                }
            }
        }

        // Update status in split pane header
        this.updateSplitPaneStatus(side, uuid);
    }

    /**
     * Update split pane status indicator
     */
    updateSplitPaneStatus(side, uuid) {
        const statusEl = document.getElementById(`${side}-pane-status`);
        if (!statusEl) return;

        const termData = this.terminals.get(uuid);
        if (!termData) return;

        const indicator = statusEl.querySelector('.status-indicator');
        const text = statusEl.querySelector('.status-text');

        // RDP-only instances don't have socket status
        if (termData.isRdpOnly) {
            if (indicator) {
                indicator.className = 'status-indicator';
                indicator.style.display = 'none';
            }
            if (text) {
                text.textContent = 'RDP Only';
            }
            return;
        }

        // Get current status based on socket state
        let status = 'disconnected';
        if (termData.socket) {
            if (termData.socket.readyState === WebSocket.OPEN) {
                status = 'connected';
            } else if (termData.socket.readyState === WebSocket.CONNECTING) {
                status = 'connecting';
            }
        }

        if (indicator) {
            indicator.style.display = '';
            indicator.className = 'status-indicator ' + status;
        }

        if (text) {
            const statusText = {
                'connecting': 'Connecting...',
                'connected': 'Connected',
                'disconnected': 'Not connected',
            };
            text.textContent = statusText[status] || 'Not connected'; // eslint-disable-line security/detect-object-injection
        }
    }

    /**
     * Initialize Split.js for split mode
     */
    initSplitJs() {
        // Destroy existing instance
        if (this.splitInstance) {
            this.splitInstance.destroy();
            this.splitInstance = null;
        }

        const leftPane = document.getElementById('left-pane');
        const rightPane = document.getElementById('right-pane');

        if (!leftPane || !rightPane || typeof Split === 'undefined') return;

        this.splitInstance = Split(['#left-pane', '#right-pane'], {
            sizes: [50, 50],
            minSize: 300,
            gutterSize: 6,
            onDragEnd: () => this.fitVisibleTerminals(),
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
                indicator.className = 'status-indicator ' + status;
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
                        text.textContent = 'Not connected';
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
