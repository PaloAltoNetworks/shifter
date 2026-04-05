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
});
