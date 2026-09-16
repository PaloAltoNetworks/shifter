/**
 * CTF admin participant-list page action tests.
 *
 * Covers the bulk "reset and send credentials" action (globalThis.sendAllInvites),
 * the per-row "send link" resend wired to .js-resend-invite buttons on
 * DOMContentLoaded, and the config read from the #participant-list-config JSON
 * payload. fetch/alert/confirm are mocked; page reloads are jsdom no-ops.
 */

require('./ctf-admin-participant-list.js');

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

function buildMarkup({ withConfig = true, participantId = 'p-1' } = {}) {
    const config = withConfig
        ? `<script id="participant-list-config" type="application/json">${JSON.stringify({
              sendInvitationsUrl: '/api/v1/ctf/send-invitations/',
              csrfToken: 'csrf-token',
          })}</script>`
        : '';
    document.body.innerHTML = `
        ${config}
        <button class="js-resend-invite" data-participant-id="${participantId}">Send link</button>
    `;
}

describe('ctf-admin-participant-list', () => {
    let fetchMock;

    beforeEach(() => {
        jest.spyOn(console, 'error').mockImplementation(() => {});
        globalThis.confirm = jest.fn().mockReturnValue(true);
        globalThis.alert = jest.fn();
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    describe('DOMContentLoaded config wiring', () => {
        test('reads the config payload and uses its URL when sending all invites', async () => {
            buildMarkup();
            document.dispatchEvent(new Event('DOMContentLoaded'));
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ success: true, sent: 1, failed: 0 }) });

            globalThis.sendAllInvites();
            await flushPromises();

            expect(fetchMock).toHaveBeenCalledWith('/api/v1/ctf/send-invitations/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': 'csrf-token',
                    'Content-Type': 'application/json',
                },
            });
        });

        test('does not throw when the config element is absent', () => {
            buildMarkup({ withConfig: false });
            expect(() => document.dispatchEvent(new Event('DOMContentLoaded'))).not.toThrow();
        });
    });

    describe('sendAllInvites', () => {
        beforeEach(() => {
            buildMarkup();
            document.dispatchEvent(new Event('DOMContentLoaded'));
        });

        test('returns without fetching when the user cancels the confirm', () => {
            globalThis.confirm.mockReturnValue(false);

            globalThis.sendAllInvites();

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('alerts the sent/failed counts on success', async () => {
            fetchMock.mockResolvedValue({
                json: () => Promise.resolve({ success: true, sent: 3, failed: 1 }),
            });

            globalThis.sendAllInvites();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Sent 3 invitation(s). Failed: 1.');
        });

        test('alerts the API error message on failure', async () => {
            fetchMock.mockResolvedValue({
                json: () => Promise.resolve({ success: false, error: 'rate limited' }),
            });

            globalThis.sendAllInvites();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: rate limited');
        });

        test('falls back to a default error message when none is returned', async () => {
            fetchMock.mockResolvedValue({
                json: () => Promise.resolve({ success: false }),
            });

            globalThis.sendAllInvites();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: Failed to send invitations');
        });

        test('alerts on network rejection', async () => {
            fetchMock.mockRejectedValue(new Error('network down'));

            globalThis.sendAllInvites();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Error sending invitations: network down');
        });
    });

    describe('resendInvite (per-row button)', () => {
        function clickResend() {
            buildMarkup({ participantId: 'p-42' });
            document.dispatchEvent(new Event('DOMContentLoaded'));
            document.querySelector('.js-resend-invite').click();
        }

        test('returns without fetching when the user cancels the confirm', () => {
            globalThis.confirm.mockReturnValue(false);

            clickResend();

            expect(fetchMock).not.toHaveBeenCalled();
        });

        test('POSTs to the resend endpoint and alerts on success', async () => {
            fetchMock.mockResolvedValue({ json: () => Promise.resolve({ success: true }) });

            clickResend();
            await flushPromises();

            expect(fetchMock).toHaveBeenCalledWith(
                '/api/v1/ctf/participants/p-42/resend-invite/',
                {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': 'csrf-token',
                        'Content-Type': 'application/json',
                    },
                },
            );
            expect(globalThis.alert).toHaveBeenCalledWith('Invitation resent successfully.');
        });

        test('alerts the API error message on failure', async () => {
            fetchMock.mockResolvedValue({
                json: () => Promise.resolve({ success: false, error: 'nope' }),
            });

            clickResend();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: nope');
        });

        test('falls back to a default error message when none is returned', async () => {
            fetchMock.mockResolvedValue({
                json: () => Promise.resolve({ success: false }),
            });

            clickResend();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Error: Failed to resend invite');
        });

        test('alerts on network rejection', async () => {
            fetchMock.mockRejectedValue(new Error('offline'));

            clickResend();
            await flushPromises();

            expect(globalThis.alert).toHaveBeenCalledWith('Error resending invite: offline');
        });
    });
});
