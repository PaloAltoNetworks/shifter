require('./dashboard-connection.js');
require('./dashboard-tiles.js');
require('./dashboard-launch.js');
require('./dashboard.js');

/**
 * Coverage for the DashboardTilesBase layer (dashboard-tiles.js): the _updateUI
 * status switch and the per-state tile renderers (provisioning, active, paused,
 * failed) including their button bindings and the launch-button reset. Driven
 * through a DashboardManager instance so template lookups and the lifecycle
 * action methods (cancel/destroy/pause/resume/dismiss) resolve on the chain.
 */
describe('DashboardTilesBase (via DashboardManager)', () => {
    let manager;

    const buildMarkup = () => `
        <button id="launch-btn">Launching...</button>
        <div id="range-tile-1"></div>
        <div id="range-tile-2"></div>
        <div id="range-tile-3"></div>
        <template id="provisioning-template">
            <div class="tile-title">Provisioning Range</div>
            <div class="status-text">Setting up infrastructure...</div>
            <button class="cancel-range-btn">Cancel</button>
        </template>
        <template id="active-template">
            <div class="tile-title">Active Range</div>
            <div class="range-agent"></div>
            <button class="destroy-btn">Destroy</button>
            <button id="pause-btn">Pause</button>
            <div class="raes-projection" hidden>
                <span class="raes-status-label">--</span>
                <span class="raes-observed-at"></span>
                <span class="raes-snapshot-summary"></span>
            </div>
            <div class="raes-participant-runtime" hidden>
                <div class="raes-participant-runtime-participants"></div>
                <div class="raes-participant-runtime-channels"></div>
            </div>
        </template>
        <template id="paused-template">
            <div class="tile-title">Paused Range</div>
            <div class="range-paused-at"></div>
            <div class="range-agent"></div>
            <button class="destroy-btn">Destroy</button>
            <button id="resume-btn">Resume</button>
        </template>
        <template id="failed-template">
            <div class="error-message"></div>
            <button class="dismiss-error-btn">Dismiss</button>
        </template>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildMarkup();
        jest.spyOn(console, 'log').mockImplementation(() => {});
        jest.spyOn(console, 'error').mockImplementation(() => {});
        // Lifecycle-action confirmations are declined so button clicks return
        // early without needing fetch; the arrow bindings still execute.
        globalThis.confirm = jest.fn().mockReturnValue(false);
        manager = new globalThis.DashboardManager({ csrfToken: 'csrf' });
    });

    afterEach(() => {
        jest.restoreAllMocks();
        jest.clearAllMocks();
    });

    const tile = () => document.getElementById('range-tile-1');

    describe('_updateUI status switch', () => {
        test('provisioning renders the provisioning tile', () => {
            manager.currentRange = { status: 'provisioning' };
            manager._updateUI();
            expect(tile().className).toBe('range-tile provisioning-tile');
            expect(tile().querySelector('.tile-title').textContent).toBe('Provisioning Range');
        });

        test('pending renders the provisioning tile', () => {
            manager.currentRange = { status: 'pending' };
            manager._updateUI();
            expect(tile().className).toBe('range-tile provisioning-tile');
        });

        test('ready renders the active tile', () => {
            manager.currentRange = { status: 'ready', agent_name: 'agent-x' };
            manager._updateUI();
            expect(tile().className).toBe('range-tile active-tile');
        });

        test('paused renders the paused tile', () => {
            manager.currentRange = { status: 'paused' };
            manager._updateUI();
            expect(tile().className).toBe('range-tile paused-tile');
        });

        test('pausing renders provisioning copy and hides the cancel button', () => {
            manager.currentRange = { status: 'pausing' };
            manager._updateUI();
            expect(tile().querySelector('.tile-title').textContent).toBe('Pausing Range');
            expect(tile().querySelector('.cancel-range-btn').style.display).toBe('none');
        });

        test('resuming renders provisioning copy and hides the cancel button', () => {
            manager.currentRange = { status: 'resuming' };
            manager._updateUI();
            expect(tile().querySelector('.tile-title').textContent).toBe('Resuming Range');
            expect(tile().querySelector('.cancel-range-btn').style.display).toBe('none');
        });

        test('failed renders the failed tile', () => {
            manager.currentRange = { status: 'failed', error_message: 'boom' };
            manager._updateUI();
            expect(tile().className).toBe('range-tile failed-tile');
            expect(tile().querySelector('.error-message').textContent).toBe('boom');
        });

        test('unknown status leaves the tile empty', () => {
            manager.currentRange = { status: 'destroyed' };
            manager._updateUI();
            expect(tile().className).toBe('range-tile empty-tile');
        });

        test('no current range resets tiles and the launch button', () => {
            manager.currentRange = null;
            manager._updateUI();
            expect(tile().className).toBe('range-tile empty-tile');
            expect(manager.launchBtn.textContent).toBe('Launch Range');
        });

        test('returns early when there is no available tile', () => {
            manager.rangeTiles = [null];
            manager.currentRange = { status: 'ready' };
            expect(() => manager._updateUI()).not.toThrow();
        });
    });

    describe('_renderProvisioningTile', () => {
        test('binds the cancel button to cancelRange', () => {
            manager.currentRange = { status: 'provisioning' };
            manager._renderProvisioningTile(tile());
            tile().querySelector('.cancel-range-btn').click();
            expect(globalThis.confirm).toHaveBeenCalled();
        });

        test('returns early without a provisioning template', () => {
            manager.provisioningTemplate = null;
            expect(() => manager._renderProvisioningTile(tile())).not.toThrow();
        });
    });

    describe('_renderActiveTile', () => {
        test('fills the agent name and binds destroy/pause buttons', () => {
            manager.currentRange = { status: 'ready', agent_name: 'agent-9' };
            manager._renderActiveTile(tile());

            expect(tile().querySelector('.range-agent').textContent).toBe('agent-9');

            tile().querySelector('.destroy-btn').click();
            tile().querySelector('#pause-btn').click();
            expect(globalThis.confirm).toHaveBeenCalledTimes(2);
        });

        test('returns early without an active template', () => {
            manager.activeTemplate = null;
            expect(() => manager._renderActiveTile(tile())).not.toThrow();
        });
    });

    describe('_renderPausedTile', () => {
        test('fills paused-at + agent and binds destroy/resume buttons', () => {
            manager.currentRange = {
                status: 'paused',
                agent_name: 'agent-3',
                paused_at: '2026-07-06T12:00:00Z',
            };
            manager._renderPausedTile(tile());

            expect(tile().querySelector('.range-agent').textContent).toBe('agent-3');
            expect(tile().querySelector('.range-paused-at').textContent).not.toBe('');

            tile().querySelector('.destroy-btn').click();
            tile().querySelector('#resume-btn').click();
            expect(globalThis.confirm).toHaveBeenCalledTimes(2);
        });

        test('returns early without a paused template', () => {
            manager.pausedTemplate = null;
            expect(() => manager._renderPausedTile(tile())).not.toThrow();
        });
    });

    describe('_renderFailedTile', () => {
        test('fills the error message and binds the dismiss button', () => {
            const dismissSpy = jest.spyOn(manager, 'dismissError');
            manager.currentRange = { status: 'failed', error_message: 'it broke' };
            manager._renderFailedTile(tile());

            expect(tile().querySelector('.error-message').textContent).toBe('it broke');
            tile().querySelector('.dismiss-error-btn').click();
            expect(dismissSpy).toHaveBeenCalled();
        });

        test('returns early without a failed template', () => {
            manager.failedTemplate = null;
            expect(() => manager._renderFailedTile(tile())).not.toThrow();
        });
    });

    describe('_formatDate', () => {
        test('formats an ISO string to a locale string', () => {
            expect(typeof manager._formatDate('2026-07-06T12:00:00Z')).toBe('string');
        });
    });

    describe('RAES projections rendered into the active tile', () => {
        beforeEach(() => {
            manager.currentRange = { status: 'ready', agent_name: 'agent-1' };
        });

        test('renders the operation projection fields when present', () => {
            manager.currentRaesProjection = {
                status: 'running',
                status_label: 'Operation running',
                observed_at: '2026-07-06T12:00:00Z',
                snapshot: { resource_count: 3, snapshot_ref: 'snap-1' },
            };
            manager._renderActiveTile(tile());

            const section = tile().querySelector('.raes-projection');
            expect(section.hidden).toBe(false);
            expect(tile().querySelector('.raes-status-label').textContent).toBe('Operation running');
            expect(tile().querySelector('.raes-observed-at').textContent).toContain('Observed');
            expect(tile().querySelector('.raes-snapshot-summary').textContent).toContain('3');
        });

        test('handles a projection with no observed_at or snapshot', () => {
            manager.currentRaesProjection = {
                status: 'accepted',
                status_label: '',
                observed_at: null,
                snapshot: null,
            };
            manager._renderActiveTile(tile());

            expect(tile().querySelector('.raes-observed-at').textContent).toBe('');
            expect(tile().querySelector('.raes-snapshot-summary').textContent).toBe('');
        });

        test('renders participant/runtime and access channels when present', () => {
            manager.currentRaesParticipantRuntime = {
                participants: [
                    {
                        participant_ref: 'p-runtime',
                        implementation: null,
                        runtime: { status: 'running' },
                    },
                    {
                        participant_ref: 'p-impl',
                        implementation: { status: 'ready' },
                        runtime: null,
                    },
                    {
                        participant_ref: 'p-unknown',
                        implementation: null,
                        runtime: null,
                    },
                ],
                access_channels: [
                    { channel: 'browser_terminal', target_ref: 'i-1' },
                    { channel: 'backend_command', target_ref: 'abc' },
                ],
            };
            manager._renderActiveTile(tile());

            const participantsEl = tile().querySelector('.raes-participant-runtime-participants');
            expect(participantsEl.textContent).toContain('p-runtime: running');
            expect(participantsEl.textContent).toContain('p-impl: ready');
            expect(participantsEl.textContent).toContain('p-unknown: unknown');

            const channelsEl = tile().querySelector('.raes-participant-runtime-channels');
            expect(channelsEl.textContent).toBe('browser_terminal, backend_command');
        });

        test('hides both RAES sections when projections are absent', () => {
            manager.currentRaesProjection = null;
            manager.currentRaesParticipantRuntime = null;
            manager._renderActiveTile(tile());

            expect(tile().querySelector('.raes-projection').hidden).toBe(true);
            expect(tile().querySelector('.raes-participant-runtime').hidden).toBe(true);
        });
    });
});
