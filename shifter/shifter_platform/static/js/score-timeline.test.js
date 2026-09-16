/**
 * CTF score timeline chart tests.
 *
 * Covers initScoreTimeline: the missing-canvas early return, the empty-timeline
 * placeholder, the populated case (labels/scores built, Chart constructed, the
 * tooltip afterLabel callback, and +/-/zero point formatting), and the fetch
 * error path. Chart and fetch are mocked. initScoreTimeline is imported via the
 * CommonJS export guard added at the end of the source.
 */

const { initScoreTimeline } = require('./score-timeline.js');

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('score-timeline', () => {
    let fetchMock;
    let ChartMock;

    beforeEach(() => {
        jest.spyOn(console, 'error').mockImplementation(() => {});
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
        ChartMock = jest.fn();
        globalThis.Chart = ChartMock;
        document.body.innerHTML =
            '<div id="wrap"><canvas id="score-timeline-chart"></canvas></div>';
    });

    afterEach(() => {
        jest.restoreAllMocks();
        delete globalThis.Chart;
        document.body.innerHTML = '';
    });

    test('no-ops and does not fetch when the canvas is absent', () => {
        initScoreTimeline('missing-canvas', '/api/timeline');
        expect(fetchMock).not.toHaveBeenCalled();
    });

    test('replaces the canvas with a placeholder when the timeline is empty', async () => {
        fetchMock.mockResolvedValue({ json: () => Promise.resolve({ timeline: [] }) });

        initScoreTimeline('score-timeline-chart', '/api/timeline');
        await flush();

        expect(document.getElementById('score-timeline-chart')).toBeNull();
        expect(document.getElementById('wrap').textContent).toBe('No score data yet.');
        expect(ChartMock).not.toHaveBeenCalled();
    });

    test('shows the placeholder when the response has no timeline field', async () => {
        fetchMock.mockResolvedValue({ json: () => Promise.resolve({}) });

        initScoreTimeline('score-timeline-chart', '/api/timeline');
        await flush();

        expect(document.getElementById('wrap').textContent).toBe('No score data yet.');
        expect(ChartMock).not.toHaveBeenCalled();
    });

    test('builds the chart data and formats +/-/zero point tooltips', async () => {
        fetchMock.mockResolvedValue({
            json: () =>
                Promise.resolve({
                    timeline: [
                        { timestamp: '2026-04-05T10:00:00Z', cumulative: 100, points: 100, label: 'Solved A' },
                        { timestamp: '2026-04-05T11:00:00Z', cumulative: 90, points: -10, label: 'Penalty' },
                        { timestamp: '2026-04-05T12:00:00Z', cumulative: 90, points: 0, label: 'No change' },
                    ],
                }),
        });

        initScoreTimeline('score-timeline-chart', '/api/timeline');
        await flush();

        expect(ChartMock).toHaveBeenCalledTimes(1);
        const [canvasArg, config] = ChartMock.mock.calls[0];
        expect(canvasArg).toBe(document.getElementById('score-timeline-chart'));
        expect(config.type).toBe('line');
        expect(config.data.datasets[0].data).toEqual([100, 90, 90]);
        expect(config.data.labels).toHaveLength(3);
        expect(config.data.labels[0]).toBeInstanceOf(Date);

        const afterLabel = config.options.plugins.tooltip.callbacks.afterLabel;
        expect(afterLabel({ dataIndex: 0 })).toBe('Solved A (+100)');
        expect(afterLabel({ dataIndex: 1 })).toBe('Penalty (-10)');
        expect(afterLabel({ dataIndex: 2 })).toBe('No change');
    });

    test('logs an error when the fetch fails', async () => {
        fetchMock.mockRejectedValue(new Error('boom'));

        initScoreTimeline('score-timeline-chart', '/api/timeline');
        await flush();

        expect(console.error).toHaveBeenCalledWith(
            'Failed to load score timeline:',
            expect.any(Error),
        );
        expect(ChartMock).not.toHaveBeenCalled();
    });
});
