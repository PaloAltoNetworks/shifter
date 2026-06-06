/**
 * Terminal Layout Base - tab / split-pane layout management for TerminalManager.
 *
 * Split out of terminal.js (Sonar S104). Holds the view/layout half of the
 * terminal manager (tab bar, pane dropdowns, layout-mode toggle, Split.js
 * integration). TerminalManager (terminal.js) extends this class and adds the
 * WebSocket connection + lifecycle half. Both are plain (non-module) scripts:
 * this file is loaded first and publishes the base class and the shared status
 * constants on globalThis so the browser script tags and the jest `require`
 * harness both resolve them.
 */
/* global Split */

const STATUS_INDICATOR_CLASS = 'status-indicator';
const NOT_CONNECTED_TEXT = 'Not connected';

class TerminalLayoutBase {
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

            const ipSuffix = instance.privateIp
                ? ` <span class="tab-ip">${this._escapeHtml(instance.privateIp)}</span>`
                : '';
            tab.innerHTML = `
                <span class="tab-status"></span>
                <span class="tab-label">${this._escapeHtml(instance.name)}${ipSuffix}</span>
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
                option.textContent = instance.privateIp
                    ? `${instance.name} (${instance.privateIp})`
                    : instance.name;
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
                indicator.className = STATUS_INDICATOR_CLASS;
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
            indicator.className = STATUS_INDICATOR_CLASS + ' ' + status;
        }

        if (text) {
            const statusText = {
                'connecting': 'Connecting...',
                'connected': 'Connected',
                'disconnected': NOT_CONNECTED_TEXT,
            };
            text.textContent = statusText[status] || NOT_CONNECTED_TEXT; // eslint-disable-line security/detect-object-injection
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
}

globalThis.TerminalLayoutBase = TerminalLayoutBase;
globalThis.STATUS_INDICATOR_CLASS = STATUS_INDICATOR_CLASS;
globalThis.NOT_CONNECTED_TEXT = NOT_CONNECTED_TEXT;
