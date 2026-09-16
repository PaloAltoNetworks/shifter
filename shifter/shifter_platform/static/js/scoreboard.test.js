// Tests for the CTF participant scoreboard: auto-refresh toggle, polling,
// live table rebuild, freeze banner, and the organizer "hidden" state.

const markup = () => `
    <div id="scoreboard-config"
         data-scoreboard-url="/api/scoreboard"
         data-solve-history-url="/api/solves"
         data-participant-id="p-1"></div>
    <button id="refresh-btn">Auto-Refresh: Off</button>
    <div class="container-fluid">
        <div class="card">
            <table id="scoreboard-table"><tbody id="scoreboard-body"></tbody></table>
        </div>
    </div>
`;

function resolvedFetch(data) {
    return jest.fn().mockResolvedValue({ json: () => Promise.resolve(data) });
}

describe('scoreboard', () => {
    let scoreboard;

    beforeEach(() => {
        jest.resetModules();
        document.body.innerHTML = markup();
        globalThis.fetch = resolvedFetch({ rankings: [] });
        // Loading the module runs initScoreboard() against the fixture above.
        scoreboard = require('./scoreboard.js');
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    describe('refreshScoreboard toggle', () => {
        test('turns auto-refresh on and fetches immediately', () => {
            scoreboard.refreshScoreboard();

            const btn = document.getElementById('refresh-btn');
            expect(btn.textContent).toBe('Auto-Refresh: On');
            expect(btn.classList.contains('btn-primary')).toBe(true);
            expect(btn.classList.contains('btn-outline-primary')).toBe(false);
            expect(globalThis.fetch).toHaveBeenCalledWith('/api/scoreboard');
        });

        test('toggles auto-refresh off on the second call', () => {
            scoreboard.refreshScoreboard();
            scoreboard.refreshScoreboard();

            const btn = document.getElementById('refresh-btn');
            expect(btn.textContent).toBe('Auto-Refresh: Off');
            expect(btn.classList.contains('btn-outline-primary')).toBe(true);
        });

        test('exposes refreshScoreboard on globalThis', () => {
            expect(globalThis.refreshScoreboard).toBe(scoreboard.refreshScoreboard);
        });

        test('polls again on the 15s interval', async () => {
            jest.useFakeTimers();
            scoreboard.refreshScoreboard();
            expect(globalThis.fetch).toHaveBeenCalledTimes(1);

            await jest.advanceTimersByTimeAsync(15000);
            expect(globalThis.fetch).toHaveBeenCalledTimes(2);
        });
    });

    describe('fetchScoreboard', () => {
        test('rebuilds the table and marks the current participant row', async () => {
            globalThis.fetch = resolvedFetch({
                rankings: [
                    { rank: 1, name: 'Alice', participant_id: 'p-1', score: 100, solve_count: 3, last_solve: '10:00' },
                    { rank: 2, name: 'Bob', participant_id: 'p-2', score: 90, solve_count: 2, last_solve: '09:00' },
                ],
                team_mode: false,
            });

            await scoreboard.fetchScoreboard();

            const rows = document.querySelectorAll('#scoreboard-body tr');
            expect(rows.length).toBe(2);
            expect(rows[0].classList.contains('table-active')).toBe(true);
            // Rank <= 3 renders inside <strong>.
            expect(rows[0].querySelector('td strong').textContent).toBe('1');
            // Current participant with a solve-history URL gets a link and a "You" badge.
            expect(rows[0].querySelector('a').getAttribute('href')).toBe('/api/solves');
            expect(rows[0].querySelector('.badge').textContent).toBe('You');
            // Non-current row is plain.
            expect(rows[1].classList.contains('table-active')).toBe(false);
            expect(rows[1].querySelector('a')).toBeNull();
        });

        test('adds a freeze banner before the card when frozen', async () => {
            globalThis.fetch = resolvedFetch({ rankings: [], frozen: true });

            await scoreboard.fetchScoreboard();

            const banner = document.getElementById('freeze-banner');
            expect(banner).not.toBeNull();
            expect(banner.style.display).toBe('');
            // Inserted immediately before the card (card.before(banner)).
            expect(banner.nextElementSibling.classList.contains('card')).toBe(true);
        });

        test('hides an existing freeze banner when no longer frozen', async () => {
            globalThis.fetch = resolvedFetch({ rankings: [], frozen: true });
            await scoreboard.fetchScoreboard();

            globalThis.fetch = resolvedFetch({ rankings: [], frozen: false });
            await scoreboard.fetchScoreboard();

            expect(document.getElementById('freeze-banner').style.display).toBe('none');
        });

        test('shows the hidden banner and stops the UI when scoreboard is hidden', async () => {
            globalThis.fetch = resolvedFetch({ scoreboard_hidden: true });

            await scoreboard.fetchScoreboard();

            expect(document.getElementById('hidden-banner')).not.toBeNull();
            expect(document.getElementById('scoreboard-table').style.display).toBe('none');
            expect(document.getElementById('refresh-btn').style.display).toBe('none');
        });

        test('hidden scoreboard clears an active auto-refresh interval', async () => {
            jest.useFakeTimers();
            // Turn auto-refresh on (creates the interval, runs an immediate fetch).
            scoreboard.refreshScoreboard();

            globalThis.fetch = resolvedFetch({ scoreboard_hidden: true });
            await scoreboard.fetchScoreboard();

            const callsBefore = globalThis.fetch.mock.calls.length;
            await jest.advanceTimersByTimeAsync(30000);
            // Interval was cleared, so no further polling occurs.
            expect(globalThis.fetch.mock.calls.length).toBe(callsBefore);
        });

        test('logs an error when the fetch fails', async () => {
            const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
            globalThis.fetch = jest.fn().mockRejectedValue(new Error('boom'));

            await scoreboard.fetchScoreboard();

            expect(errSpy).toHaveBeenCalledWith('Failed to refresh scoreboard:', expect.any(Error));
            errSpy.mockRestore();
        });
    });

    describe('rebuildScoreboardTable', () => {
        test('renders team rows with a member-count column and plain high ranks', () => {
            // Seed a stale row so the rebuild must clear existing children first.
            document.getElementById('scoreboard-body').innerHTML = '<tr><td>stale</td></tr>';
            scoreboard.rebuildScoreboardTable(
                [{ rank: 4, name: 'Team B', score: 50, solve_count: 1, member_count: 3, last_solve: null }],
                true
            );

            const cells = document.querySelectorAll('#scoreboard-body tr td');
            // rank, name, member_count, score, solves, last_solve
            expect(cells.length).toBe(6);
            expect(cells[0].querySelector('strong')).toBeNull(); // rank > 3
            expect(cells[0].textContent).toBe('4');
            expect(cells[2].textContent).toBe('3'); // member_count column
            expect(cells[5].textContent).toBe('-'); // last_solve fallback
        });

        test('renders a current-user row without a link when no solve-history URL is set', async () => {
            // Reload with an empty solve-history URL so the link branch is skipped.
            jest.resetModules();
            document.body.innerHTML = markup().replace('data-solve-history-url="/api/solves"', 'data-solve-history-url=""');
            const sb = require('./scoreboard.js');

            sb.rebuildScoreboardTable(
                [{ rank: 1, name: 'Alice', participant_id: 'p-1', score: 100, solve_count: 1, last_solve: '10:00' }],
                false
            );

            const row = document.querySelector('#scoreboard-body tr');
            expect(row.classList.contains('table-active')).toBe(true);
            expect(row.querySelector('a')).toBeNull();
            expect(row.querySelector('.badge').textContent).toBe('You');
        });

        test('returns early when the tbody is missing', () => {
            document.getElementById('scoreboard-body').remove();
            expect(() => scoreboard.rebuildScoreboardTable([{ rank: 1 }], false)).not.toThrow();
        });
    });

    describe('initScoreboard', () => {
        test('does nothing when the config element is absent', () => {
            document.body.innerHTML = '';
            expect(() => scoreboard.initScoreboard()).not.toThrow();
        });

        test('defers init to DOMContentLoaded while the document is loading', () => {
            jest.resetModules();
            Object.defineProperty(document, 'readyState', { configurable: true, get: () => 'loading' });
            try {
                document.body.innerHTML = markup();
                const sb = require('./scoreboard.js');
                document.dispatchEvent(new Event('DOMContentLoaded'));
                // Config was picked up via the deferred initScoreboard listener.
                globalThis.fetch = resolvedFetch({ rankings: [] });
                sb.refreshScoreboard();
                expect(globalThis.fetch).toHaveBeenCalledWith('/api/scoreboard');
            } finally {
                delete document.readyState;
            }
        });
    });
});
