require('./ctf-ranges.js');

function buildDOM() {
    return `
        <button id="btn-provision-all">Provision All Ranges</button>
        <div id="provision-progress" style="display: none;"></div>
        <div id="spare-pool-summary"></div>
        <input type="number" id="spare-pool-count" min="0" value="0">
        <button id="btn-set-spare-pool">Update</button>
        <table>
            <tr>
                <td>
                    <button class="btn-provision" data-participant-id="aaa-111">Provision</button>
                </td>
            </tr>
            <tr>
                <td>
                    <button class="btn-destroy" data-participant-id="bbb-222">Destroy</button>
                </td>
            </tr>
        </table>
    `;
}

describe('CTFRangeManager', () => {
    let manager;
    let fetchMock;

    beforeEach(() => {
        document.body.innerHTML = buildDOM();

        fetchMock = jest.fn().mockResolvedValue({
            ok: true,
            json: () => Promise.resolve({ successful: 2, failed: 0, errors: [] }),
        });
        globalThis.fetch = fetchMock;
        globalThis.confirm = jest.fn().mockReturnValue(true);
        globalThis.alert = jest.fn();

        manager = new globalThis.CTFRangeManager({
            csrfToken: 'test-csrf',
            provisionAllUrl: '/ctf/api/events/evt-1/ranges/provision/',
            rangeListUrl: '/ctf/api/events/evt-1/ranges/',
            spareProvisionUrl: '/ctf/api/events/evt-1/spares/',
        });
        manager._reload = jest.fn();
        manager.init();
    });

    afterEach(() => {
        if (manager) manager._stopProgressPolling();
    });

    describe('provisionAll', () => {
        test('sends POST to provision all URL with CSRF token', async () => {
            await manager.provisionAll();

            expect(fetchMock).toHaveBeenCalledWith(
                '/ctf/api/events/evt-1/ranges/provision/',
                {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': 'test-csrf',
                        'Content-Type': 'application/json',
                    },
                }
            );
        });

        test('does not call fetch if user cancels confirmation', async () => {
            globalThis.confirm.mockReturnValue(false);

            await manager.provisionAll();

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('queues background provisioning and starts polling without a blocking alert', async () => {
            let pollSpy = jest.spyOn(manager, 'startProgressPolling').mockImplementation(() => {});
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ event_id: 'evt-1', status: 'queued', task_id: 't1' }),
            });

            await manager.provisionAll();

            expect(globalThis.alert).not.toHaveBeenCalled();
            expect(pollSpy).toHaveBeenCalled();
        });

        test('shows error on non-ok response and does not poll', async () => {
            let pollSpy = jest.spyOn(manager, 'startProgressPolling').mockImplementation(() => {});
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'Event not found' }),
            });

            await manager.provisionAll();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: Event not found');
            expect(pollSpy).not.toHaveBeenCalled();
            expect(manager._reload).not.toHaveBeenCalled();
        });

        test('disables button while loading', async () => {
            jest.spyOn(manager, 'startProgressPolling').mockImplementation(() => {});
            let btn = document.getElementById('btn-provision-all');

            // Hold the fetch so we can check intermediate state
            let resolveResponse;
            fetchMock.mockReturnValue(new Promise(function(resolve) {
                resolveResponse = resolve;
            }));

            let promise = manager.provisionAll();

            expect(btn.disabled).toBe(true);
            expect(btn.textContent).toBe('Queuing...');

            resolveResponse({
                ok: true,
                json: () => Promise.resolve({ status: 'queued', task_id: 't1' }),
            });

            await promise;

            expect(btn.disabled).toBe(false);
        });
    });

    describe('progress polling', () => {
        test('renders counts and reloads when provisioning is complete', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    progress: { counts: { total: 2, ready: 2, provisioning: 0, error: 0, not_assigned: 0 }, task: null },
                }),
            });

            await manager._pollProgress();

            let el = document.getElementById('provision-progress');
            expect(el.textContent).toContain('ready 2');
            expect(manager._reload).toHaveBeenCalled();
        });

        test('keeps polling while a spin-up task is active', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    progress: { counts: { total: 2, provisioning: 1 }, task: { status: 'running' } },
                }),
            });

            await manager._pollProgress();

            expect(manager._reload).not.toHaveBeenCalled();
        });

        test('startProgressPolling is idempotent', () => {
            jest.spyOn(manager, '_pollProgress').mockResolvedValue(undefined);

            manager.startProgressPolling();
            let first = manager.statusPollInterval;
            manager.startProgressPolling();

            expect(manager.statusPollInterval).toBe(first);
        });
    });

    describe('provisionOne', () => {
        test('sends POST to participant provision URL', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    participant_id: 'aaa-111',
                    status: 'provisioning',
                }),
            });

            let btn = document.querySelector('.btn-provision');
            await manager.provisionOne('aaa-111', btn);

            expect(fetchMock).toHaveBeenCalledWith(
                '/ctf/api/participants/aaa-111/range/provision/',
                {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': 'test-csrf',
                        'Content-Type': 'application/json',
                    },
                }
            );
        });

        test('does not call fetch if user cancels', async () => {
            globalThis.confirm.mockReturnValue(false);
            let btn = document.querySelector('.btn-provision');

            await manager.provisionOne('aaa-111', btn);

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('reloads page on success', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ participant_id: 'aaa-111', status: 'provisioning' }),
            });

            let btn = document.querySelector('.btn-provision');
            await manager.provisionOne('aaa-111', btn);

            expect(manager._reload).toHaveBeenCalled();
        });

        test('shows error and re-enables button on failure', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'No agent configured' }),
            });

            let btn = document.querySelector('.btn-provision');
            await manager.provisionOne('aaa-111', btn);

            expect(globalThis.alert).toHaveBeenCalledWith('Error: No agent configured');
            expect(btn.disabled).toBe(false);
            expect(manager._reload).not.toHaveBeenCalled();
        });
    });

    describe('destroyOne', () => {
        test('sends POST to participant destroy URL', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ participant_id: 'bbb-222', status: 'destroyed' }),
            });

            let btn = document.querySelector('.btn-destroy');
            await manager.destroyOne('bbb-222', btn);

            expect(fetchMock).toHaveBeenCalledWith(
                '/ctf/api/participants/bbb-222/range/destroy/',
                {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': 'test-csrf',
                        'Content-Type': 'application/json',
                    },
                }
            );
        });

        test('does not call fetch if user cancels', async () => {
            globalThis.confirm.mockReturnValue(false);
            let btn = document.querySelector('.btn-destroy');

            await manager.destroyOne('bbb-222', btn);

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('reloads page on success', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ participant_id: 'bbb-222', status: 'destroyed' }),
            });

            let btn = document.querySelector('.btn-destroy');
            await manager.destroyOne('bbb-222', btn);

            expect(manager._reload).toHaveBeenCalled();
        });

        test('shows error and re-enables button on failure', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'No range assigned' }),
            });

            let btn = document.querySelector('.btn-destroy');
            await manager.destroyOne('bbb-222', btn);

            expect(globalThis.alert).toHaveBeenCalledWith('Error: No range assigned');
            expect(btn.disabled).toBe(false);
        });
    });

    describe('setSparePool', () => {
        test('posts the count from the input to the spare-pool URL', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    event_id: 'evt-1', target_count: 3, existing: 0, created: 3,
                }),
            });
            document.getElementById('spare-pool-count').value = '3';

            await manager.setSparePool();

            expect(fetchMock).toHaveBeenCalledWith(
                '/ctf/api/events/evt-1/spares/',
                {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': 'test-csrf',
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ count: 3 }),
                }
            );
        });

        test('renders the returned summary into the summary element', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    event_id: 'evt-1', target_count: 3, existing: 0, created: 3,
                }),
            });
            document.getElementById('spare-pool-count').value = '3';

            await manager.setSparePool();

            let el = document.getElementById('spare-pool-summary');
            expect(el.textContent).toContain('3');
        });

        test('shows error on non-ok response and does not throw', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'count must be non-negative' }),
            });
            document.getElementById('spare-pool-count').value = '-1';

            await manager.setSparePool();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: count must be non-negative');
        });

        test('re-enables the button after completion', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    event_id: 'evt-1', target_count: 1, existing: 0, created: 1,
                }),
            });
            document.getElementById('spare-pool-count').value = '1';

            await manager.setSparePool();

            let btn = document.getElementById('btn-set-spare-pool');
            expect(btn.disabled).toBe(false);
        });
    });

    describe('init', () => {
        test('binds click on provision-all button', async () => {
            let btn = document.getElementById('btn-provision-all');
            btn.click();

            // confirm was called, so binding worked
            expect(globalThis.confirm).toHaveBeenCalled();
        });

        test('binds click on individual provision buttons', async () => {
            let btn = document.querySelector('.btn-provision');
            btn.click();

            expect(globalThis.confirm).toHaveBeenCalled();
        });

        test('binds click on individual destroy buttons', async () => {
            let btn = document.querySelector('.btn-destroy');
            btn.click();

            expect(globalThis.confirm).toHaveBeenCalled();
        });

        test('binds click on the set-spare-pool button', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    event_id: 'evt-1', target_count: 0, existing: 0, created: 0,
                }),
            });
            let btn = document.getElementById('btn-set-spare-pool');

            btn.click();

            expect(fetchMock).toHaveBeenCalled();
        });
    });

    describe('_setButtonLoading / _clearButtonLoading', () => {
        test('disables button and sets text', () => {
            let btn = document.getElementById('btn-provision-all');

            manager._setButtonLoading(btn, 'Loading...');

            expect(btn.disabled).toBe(true);
            expect(btn.textContent).toBe('Loading...');
        });

        test('re-enables button and restores text', () => {
            let btn = document.getElementById('btn-provision-all');

            manager._setButtonLoading(btn, 'Loading...');
            manager._clearButtonLoading(btn, 'Fallback');

            expect(btn.disabled).toBe(false);
            expect(btn.textContent).toBe('Provision All Ranges');
        });

        test('handles null button gracefully', () => {
            expect(() => manager._setButtonLoading(null, 'x')).not.toThrow();
            expect(() => manager._clearButtonLoading(null, 'x')).not.toThrow();
        });
    });
});
