require('./dashboard.js');

describe('DashboardManager destroyRange', () => {
    let dashboard;
    let fetchMock;

    beforeEach(() => {
        document.body.innerHTML = `
            <div id="no-range-state"></div>
            <div id="provisioning-state"></div>
            <div id="active-range-state"></div>
            <div id="paused-range-state"></div>
            <div id="failed-state"></div>
        `;

        fetchMock = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({}),
        });
        globalThis.fetch = fetchMock;
        globalThis.confirm = jest.fn().mockReturnValue(true);

        dashboard = new globalThis.DashboardManager({
            csrfToken: 'test-csrf-token',
            rangeUrl: '/range',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard.currentRange = { request_id: 'abc-123-def', status: 'ready' };
    });

    test('sends request_id in request body', async () => {
        await dashboard.destroyRange();

        expect(fetchMock).toHaveBeenCalledWith('/destroy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': 'test-csrf-token',
            },
            body: JSON.stringify({ request_id: 'abc-123-def' }),
        });
    });

    test('does not call fetch if user cancels confirmation', async () => {
        globalThis.confirm.mockReturnValue(false);

        await dashboard.destroyRange();

        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('DashboardManager dropdown initialization', () => {
    const buildScenarioMarkup = () => `
        <div class="shifter-dropdown" id="scenario-dropdown">
            <input type="hidden" id="scenario-select-value" value="basic">
        </div>
    `;

    beforeEach(() => {
        document.body.innerHTML = buildScenarioMarkup();
        globalThis.ShifterDropdown = { init: jest.fn() };
    });

    test('uses ShifterDropdown.init for explicit init', () => {
        const dashboard = new globalThis.DashboardManager({
            csrfToken: 'csrf',
            statusUrl: '/status',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard._initScenarioDropdown();

        expect(globalThis.ShifterDropdown.init).toHaveBeenCalledWith(dashboard.scenarioDropdown);
    });
});

describe('DashboardManager status polling', () => {
    let dashboard;
    let fetchMock;

    beforeEach(() => {
        jest.useFakeTimers();

        document.body.innerHTML = `
            <div id="no-range-state"></div>
            <div id="provisioning-state"></div>
            <div id="active-range-state"></div>
            <div id="paused-range-state"></div>
            <div id="failed-state"></div>
        `;

        fetchMock = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { range_id: 42, status: 'provisioning' } }),
        });
        globalThis.fetch = fetchMock;

        dashboard = new globalThis.DashboardManager({
            csrfToken: 'test-csrf-token',
            rangeUrl: '/range',
            launchUrl: '/launch',
            cancelUrl: '/cancel',
            destroyUrl: '/destroy',
            agentsUrl: '/agents',
        });

        dashboard.currentRange = { range_id: 42, status: 'provisioning' };
    });

    afterEach(() => {
        jest.useRealTimers();
        dashboard._stopStatusPolling();
    });

    test('_startStatusPolling creates interval', () => {
        expect(dashboard.statusPollInterval).toBeNull();

        dashboard._startStatusPolling();

        expect(dashboard.statusPollInterval).not.toBeNull();
    });

    test('_startStatusPolling does not create multiple intervals', () => {
        dashboard._startStatusPolling();
        const firstInterval = dashboard.statusPollInterval;

        dashboard._startStatusPolling();

        expect(dashboard.statusPollInterval).toBe(firstInterval);
    });

    test('_stopStatusPolling clears interval', () => {
        dashboard._startStatusPolling();
        expect(dashboard.statusPollInterval).not.toBeNull();

        dashboard._stopStatusPolling();

        expect(dashboard.statusPollInterval).toBeNull();
    });

    test('polling fetches range status at interval', async () => {
        dashboard._startStatusPolling();

        // Advance past the polling interval
        jest.advanceTimersByTime(30000);

        // Allow promises to resolve
        await Promise.resolve();

        expect(fetchMock).toHaveBeenCalledWith('/range', {
            headers: { 'Accept': 'application/json' },
        });
    });

    test('polling updates UI when stable state detected', async () => {
        fetchMock.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { range_id: 42, status: 'ready' } }),
        });

        dashboard._startStatusPolling();
        await jest.advanceTimersByTimeAsync(30000);

        expect(dashboard.currentRange.status).toBe('ready');
    });

    test('polling stops when stable state detected', async () => {
        fetchMock.mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { range_id: 42, status: 'ready' } }),
        });

        dashboard._startStatusPolling();
        await jest.advanceTimersByTimeAsync(30000);

        expect(dashboard.statusPollInterval).toBeNull();
    });

    test('polling stops when no current range', async () => {
        dashboard._startStatusPolling();
        dashboard.currentRange = null;

        jest.advanceTimersByTime(30000);
        await Promise.resolve();

        expect(dashboard.statusPollInterval).toBeNull();
    });

    test('_closeStatusSocket stops polling', () => {
        dashboard._startStatusPolling();
        expect(dashboard.statusPollInterval).not.toBeNull();

        dashboard._closeStatusSocket();

        expect(dashboard.statusPollInterval).toBeNull();
    });
});

describe('DashboardManager ACES projection', () => {
    const buildTileMarkup = () => `
        <div id="range-tile-1"></div>
        <template id="active-template">
            <div class="tile-title">Active Range</div>
            <div class="aces-projection" hidden>
                <div class="aces-projection-title">ACES Operation</div>
                <span class="aces-status-label">--</span>
                <span class="aces-observed-at"></span>
                <span class="aces-snapshot-summary"></span>
            </div>
        </template>
    `;

    let dashboard;

    beforeEach(() => {
        document.body.innerHTML = buildTileMarkup();
        dashboard = new globalThis.DashboardManager({ csrfToken: 'csrf' });
        dashboard.currentRange = { request_id: 'abc', status: 'ready' };
    });

    test('renders projection fields into the active tile via textContent', () => {
        dashboard.currentAcesProjection = {
            status: 'running',
            status_label: 'Operation running',
            observed_at: '2026-07-06T12:00:00Z',
            snapshot: { resource_count: 2, snapshot_ref: 'snap-1' },
        };

        const tile = document.getElementById('range-tile-1');
        dashboard._renderActiveTile(tile);

        const section = tile.querySelector('.aces-projection');
        expect(section.hidden).toBe(false);
        expect(tile.querySelector('.aces-status-label').textContent).toBe('Operation running');
        expect(tile.querySelector('.aces-snapshot-summary').textContent).toContain('2');
    });

    test('hides the projection section when no projection is present', () => {
        dashboard.currentAcesProjection = null;

        const tile = document.getElementById('range-tile-1');
        dashboard._renderActiveTile(tile);

        expect(tile.querySelector('.aces-projection').hidden).toBe(true);
    });

    test('inserts ACES-derived values as text, never as HTML', () => {
        dashboard.currentAcesProjection = {
            status: 'running',
            status_label: '<img src=x onerror=alert(1)>',
            observed_at: null,
            snapshot: null,
        };

        const tile = document.getElementById('range-tile-1');
        dashboard._renderActiveTile(tile);

        const labelEl = tile.querySelector('.aces-status-label');
        // Rendered as literal text; no child <img> element is created.
        expect(labelEl.querySelector('img')).toBeNull();
        expect(labelEl.textContent).toBe('<img src=x onerror=alert(1)>');
    });

    test('loadRange stores the aces_projection from the response', async () => {
        const projection = { status: 'succeeded', status_label: 'Operation succeeded', snapshot: null };
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ range: { request_id: 'abc', status: 'ready' }, aces_projection: projection }),
        });
        dashboard.rangeUrl = '/range';

        await dashboard.loadRange();

        expect(dashboard.currentAcesProjection).toEqual(projection);
    });

    test('ACES states are not part of the transitional-state set', () => {
        for (const acesState of ['accepted', 'running', 'succeeded', 'failed', 'cancelled']) {
            expect(dashboard._isTransitionalState(acesState)).toBe(false);
        }
    });
});

describe('DashboardManager ACES participant/runtime projection', () => {
    const buildTileMarkup = () => `
        <div id="range-tile-1"></div>
        <template id="active-template">
            <div class="tile-title">Active Range</div>
            <div class="aces-participant-runtime" hidden>
                <div class="aces-participant-runtime-title">ACES Participants</div>
                <div class="aces-participant-runtime-participants"></div>
                <div class="aces-participant-runtime-channels"></div>
            </div>
        </template>
    `;

    let dashboard;

    beforeEach(() => {
        document.body.innerHTML = buildTileMarkup();
        dashboard = new globalThis.DashboardManager({ csrfToken: 'csrf' });
        dashboard.currentRange = { request_id: 'abc', status: 'ready' };
    });

    test('renders participant/runtime fields into the active tile via textContent', () => {
        dashboard.currentAcesParticipantRuntime = {
            participants: [
                {
                    participant_ref: 'ctf-participant-1',
                    implementation: null,
                    runtime: { status: 'running', status_reason: null, runtime_ref: 'runtime-1', observed_at: null },
                },
            ],
            access_channels: [
                { channel: 'browser_terminal', target_ref: 'instance-1' },
                { channel: 'backend_command', target_ref: 'abc' },
            ],
        };

        const tile = document.getElementById('range-tile-1');
        dashboard._renderActiveTile(tile);

        const section = tile.querySelector('.aces-participant-runtime');
        expect(section.hidden).toBe(false);
        expect(tile.querySelector('.aces-participant-runtime-participants').textContent).toContain(
            'ctf-participant-1'
        );
        expect(tile.querySelector('.aces-participant-runtime-participants').textContent).toContain('running');
        expect(tile.querySelector('.aces-participant-runtime-channels').textContent).toContain('browser_terminal');
        expect(tile.querySelector('.aces-participant-runtime-channels').textContent).toContain('backend_command');
    });

    test('hides the participant/runtime section when no projection is present', () => {
        dashboard.currentAcesParticipantRuntime = null;

        const tile = document.getElementById('range-tile-1');
        dashboard._renderActiveTile(tile);

        expect(tile.querySelector('.aces-participant-runtime').hidden).toBe(true);
    });

    test('inserts ACES-derived participant refs as text, never as HTML', () => {
        dashboard.currentAcesParticipantRuntime = {
            participants: [
                {
                    participant_ref: '<img src=x onerror=alert(1)>',
                    implementation: null,
                    runtime: { status: 'running', status_reason: null, runtime_ref: null, observed_at: null },
                },
            ],
            access_channels: [],
        };

        const tile = document.getElementById('range-tile-1');
        dashboard._renderActiveTile(tile);

        const participantsEl = tile.querySelector('.aces-participant-runtime-participants');
        // Rendered as literal text; no child <img> element is created.
        expect(participantsEl.querySelector('img')).toBeNull();
        expect(participantsEl.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    test('loadRange stores the aces_participant_runtime from the response', async () => {
        const participantRuntime = { participants: [], access_channels: [] };
        globalThis.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: () =>
                Promise.resolve({
                    range: { request_id: 'abc', status: 'ready' },
                    aces_projection: null,
                    aces_participant_runtime: participantRuntime,
                }),
        });
        dashboard.rangeUrl = '/range';

        await dashboard.loadRange();

        expect(dashboard.currentAcesParticipantRuntime).toEqual(participantRuntime);
    });
});
