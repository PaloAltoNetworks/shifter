/**
 * CTF Event Timing (CTF-702)
 *
 * Handles:
 * - Converting event start/end times to participant's local timezone
 * - Displaying a live countdown timer until event start or end
 */

(function () {
    'use strict';

    var SECOND = 1000;
    var MINUTE = 60 * SECOND;
    var HOUR = 60 * MINUTE;
    var DAY = 24 * HOUR;

    /**
     * Format a Date in the browser's local timezone.
     * Example output: "Apr 05, 2026 14:30 EDT"
     */
    function formatLocalTime(date) {
        return date.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            timeZoneName: 'short',
        });
    }

    /**
     * Format a duration in milliseconds as "Xd Xh Xm Xs".
     * Omits zero-value leading components (e.g. "2h 05m 03s" not "0d 2h 05m 03s").
     */
    function formatDuration(ms) {
        if (ms <= 0) return '0s';

        var days = Math.floor(ms / DAY);
        var hours = Math.floor((ms % DAY) / HOUR);
        var minutes = Math.floor((ms % HOUR) / MINUTE);
        var seconds = Math.floor((ms % MINUTE) / SECOND);

        var parts = [];
        if (days > 0) parts.push(days + 'd');
        if (days > 0 || hours > 0) parts.push(hours + 'h');
        if (days > 0 || hours > 0 || minutes > 0) {
            parts.push((minutes < 10 && parts.length > 0 ? '0' : '') + minutes + 'm');
        }
        parts.push((seconds < 10 && parts.length > 0 ? '0' : '') + seconds + 's');

        return parts.join(' ');
    }

    /**
     * Convert the static schedule display to local timezone.
     */
    function initLocalTimes() {
        var schedule = document.getElementById('ctf-schedule');
        if (!schedule) return;

        var startISO = schedule.getAttribute('data-event-start');
        var endISO = schedule.getAttribute('data-event-end');

        if (startISO) {
            var startEl = document.getElementById('ctf-start-time');
            if (startEl) startEl.textContent = formatLocalTime(new Date(startISO));
        }

        if (endISO) {
            var endEl = document.getElementById('ctf-end-time');
            if (endEl) endEl.textContent = formatLocalTime(new Date(endISO));
        }
    }

    /**
     * Initialize and run the countdown timer.
     */
    function initCountdown() {
        var card = document.getElementById('ctf-countdown-card');
        if (!card) return;

        var startISO = card.getAttribute('data-event-start');
        var endISO = card.getAttribute('data-event-end');
        if (!startISO || !endISO) return;

        var eventStart = new Date(startISO);
        var eventEnd = new Date(endISO);
        var labelEl = document.getElementById('ctf-countdown-label');
        var timerEl = document.getElementById('ctf-countdown-timer');

        function update() {
            var now = new Date();
            var diff;

            if (now < eventStart) {
                labelEl.textContent = 'Event starts in';
                diff = eventStart - now;
                timerEl.textContent = formatDuration(diff);
                card.style.display = '';
            } else if (now < eventEnd) {
                labelEl.textContent = 'Time remaining';
                diff = eventEnd - now;
                timerEl.textContent = formatDuration(diff);
                card.style.display = '';
            } else {
                labelEl.textContent = '';
                timerEl.textContent = 'Event has ended';
                card.style.display = '';
                clearInterval(intervalId);
            }
        }

        update();
        var intervalId = setInterval(update, SECOND);
    }

    // Run on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            initLocalTimes();
            initCountdown();
        });
    } else {
        initLocalTimes();
        initCountdown();
    }

    // Expose for testing
    if (typeof module !== 'undefined' && module.exports) { // eslint-disable-line no-undef
        module.exports = { formatLocalTime: formatLocalTime, formatDuration: formatDuration }; // eslint-disable-line no-undef
    }
})();
