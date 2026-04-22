require('./ctf-ranges.js');

function buildDOM() {
    return `
        <button id="btn-provision-all">Provision All Ranges</button>
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
        });
        manager._reload = jest.fn();
        manager.init();
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

        test('shows success message and reloads on success', async () => {
            await manager.provisionAll();

            expect(globalThis.alert).toHaveBeenCalledWith(
                'Provisioned: 2, Failed: 0'
            );
            expect(manager._reload).toHaveBeenCalled();
        });

        test('shows errors in alert when some fail', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({
                    successful: 1,
                    failed: 1,
                    errors: [{ participant_id: 'p1', error: 'No agent configured' }],
                }),
            });

            await manager.provisionAll();

            expect(globalThis.alert).toHaveBeenCalledWith(
                expect.stringContaining('No agent configured')
            );
        });

        test('shows error on non-ok response', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'Event not found' }),
            });

            await manager.provisionAll();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: Event not found');
            expect(manager._reload).not.toHaveBeenCalled();
        });

        test('disables button while loading', async () => {
            var btn = document.getElementById('btn-provision-all');

            // Hold the fetch so we can check intermediate state
            var resolveResponse;
            fetchMock.mockReturnValue(new Promise(function(resolve) {
                resolveResponse = resolve;
            }));

            var promise = manager.provisionAll();

            expect(btn.disabled).toBe(true);
            expect(btn.textContent).toBe('Provisioning...');

            resolveResponse({
                ok: true,
                json: () => Promise.resolve({ successful: 0, failed: 0, errors: [] }),
            });

            await promise;

            expect(btn.disabled).toBe(false);
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

            var btn = document.querySelector('.btn-provision');
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
            var btn = document.querySelector('.btn-provision');

            await manager.provisionOne('aaa-111', btn);

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('reloads page on success', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ participant_id: 'aaa-111', status: 'provisioning' }),
            });

            var btn = document.querySelector('.btn-provision');
            await manager.provisionOne('aaa-111', btn);

            expect(manager._reload).toHaveBeenCalled();
        });

        test('shows error and re-enables button on failure', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'No agent configured' }),
            });

            var btn = document.querySelector('.btn-provision');
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

            var btn = document.querySelector('.btn-destroy');
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
            var btn = document.querySelector('.btn-destroy');

            await manager.destroyOne('bbb-222', btn);

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('reloads page on success', async () => {
            fetchMock.mockResolvedValue({
                ok: true,
                json: () => Promise.resolve({ participant_id: 'bbb-222', status: 'destroyed' }),
            });

            var btn = document.querySelector('.btn-destroy');
            await manager.destroyOne('bbb-222', btn);

            expect(manager._reload).toHaveBeenCalled();
        });

        test('shows error and re-enables button on failure', async () => {
            fetchMock.mockResolvedValue({
                ok: false,
                json: () => Promise.resolve({ error: 'No range assigned' }),
            });

            var btn = document.querySelector('.btn-destroy');
            await manager.destroyOne('bbb-222', btn);

            expect(globalThis.alert).toHaveBeenCalledWith('Error: No range assigned');
            expect(btn.disabled).toBe(false);
        });
    });

    describe('init', () => {
        test('binds click on provision-all button', async () => {
            var btn = document.getElementById('btn-provision-all');
            btn.click();

            // confirm was called, so binding worked
            expect(globalThis.confirm).toHaveBeenCalled();
        });

        test('binds click on individual provision buttons', async () => {
            var btn = document.querySelector('.btn-provision');
            btn.click();

            expect(globalThis.confirm).toHaveBeenCalled();
        });

        test('binds click on individual destroy buttons', async () => {
            var btn = document.querySelector('.btn-destroy');
            btn.click();

            expect(globalThis.confirm).toHaveBeenCalled();
        });
    });

    describe('_setButtonLoading / _clearButtonLoading', () => {
        test('disables button and sets text', () => {
            var btn = document.getElementById('btn-provision-all');

            manager._setButtonLoading(btn, 'Loading...');

            expect(btn.disabled).toBe(true);
            expect(btn.textContent).toBe('Loading...');
        });

        test('re-enables button and restores text', () => {
            var btn = document.getElementById('btn-provision-all');

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
