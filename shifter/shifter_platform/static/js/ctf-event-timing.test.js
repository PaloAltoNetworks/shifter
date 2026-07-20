var timing = require('./ctf-event-timing.js');

describe('ctf-event-timing', () => {
    describe('formatDuration', () => {
        test('returns 0s for zero or negative', () => {
            expect(timing.formatDuration(0)).toBe('0s');
            expect(timing.formatDuration(-1000)).toBe('0s');
        });

        test('formats seconds only', () => {
            expect(timing.formatDuration(5000)).toBe('5s');
            expect(timing.formatDuration(59000)).toBe('59s');
        });

        test('formats minutes and seconds', () => {
            expect(timing.formatDuration(65000)).toBe('1m 05s');
            expect(timing.formatDuration(600000)).toBe('10m 00s');
        });

        test('formats hours, minutes, seconds', () => {
            expect(timing.formatDuration(3661000)).toBe('1h 01m 01s');
            expect(timing.formatDuration(7200000)).toBe('2h 00m 00s');
        });

        test('formats days', () => {
            // 1 day, 2 hours, 3 minutes, 4 seconds
            var ms = (1 * 86400 + 2 * 3600 + 3 * 60 + 4) * 1000;
            expect(timing.formatDuration(ms)).toBe('1d 2h 03m 04s');
        });
    });

    describe('formatLocalTime', () => {
        test('returns a non-empty string for a valid date', () => {
            var result = timing.formatLocalTime(new Date('2026-04-05T14:30:00Z'));
            expect(typeof result).toBe('string');
            expect(result.length).toBeGreaterThan(0);
        });

        test('includes year component', () => {
            var result = timing.formatLocalTime(new Date('2026-04-05T14:30:00Z'));
            expect(result).toMatch(/2026/);
        });
    });

    describe('initCountdown', () => {
        var DAY_MS = 24 * 60 * 60 * 1000;

        function isoFromNow(offsetMs) {
            return new Date(Date.now() + offsetMs).toISOString();
        }

        function setupCard(attrs) {
            document.body.innerHTML =
                '<div id="ctf-countdown-card" class="d-none"></div>' +
                '<span id="ctf-countdown-label"></span>' +
                '<span id="ctf-countdown-timer"></span>';
            var card = document.getElementById('ctf-countdown-card');
            if (attrs.start) card.setAttribute('data-event-start', attrs.start);
            if (attrs.end) card.setAttribute('data-event-end', attrs.end);
            if (attrs.status) card.setAttribute('data-event-status', attrs.status);
            return card;
        }

        beforeEach(() => {
            jest.useFakeTimers();
        });

        afterEach(() => {
            jest.clearAllTimers();
            jest.useRealTimers();
            document.body.innerHTML = '';
        });

        test('no-ops when the countdown card is absent', () => {
            document.body.innerHTML = '';
            expect(() => timing.initCountdown()).not.toThrow();
        });

        test('reveals the card and counts down to a future start', () => {
            var card = setupCard({ start: isoFromNow(DAY_MS), end: isoFromNow(2 * DAY_MS) });
            timing.initCountdown();
            expect(card.classList.contains('d-none')).toBe(false);
            expect(document.getElementById('ctf-countdown-label').textContent).toBe('Event starts in');
        });

        test('reveals the card and shows time remaining while in progress', () => {
            var card = setupCard({ start: isoFromNow(-DAY_MS), end: isoFromNow(DAY_MS) });
            timing.initCountdown();
            expect(card.classList.contains('d-none')).toBe(false);
            expect(document.getElementById('ctf-countdown-label').textContent).toBe('Time remaining');
        });

        test('reveals the card and shows ended after the end time', () => {
            var card = setupCard({ start: isoFromNow(-2 * DAY_MS), end: isoFromNow(-DAY_MS) });
            timing.initCountdown();
            expect(card.classList.contains('d-none')).toBe(false);
            expect(document.getElementById('ctf-countdown-timer').textContent).toBe('Event has ended');
        });

        test('shows ended for a completed event regardless of timestamps', () => {
            var card = setupCard({
                start: isoFromNow(-DAY_MS),
                end: isoFromNow(DAY_MS),
                status: 'completed',
            });
            timing.initCountdown();
            expect(card.classList.contains('d-none')).toBe(false);
            expect(document.getElementById('ctf-countdown-timer').textContent).toBe('Event has ended');
        });

        test('stays hidden for a cancelled event', () => {
            var card = setupCard({
                start: isoFromNow(DAY_MS),
                end: isoFromNow(2 * DAY_MS),
                status: 'cancelled',
            });
            timing.initCountdown();
            expect(card.classList.contains('d-none')).toBe(true);
        });
    });
});
