// Tests for admin-participant-detail.js — covers resendInvite, disqualifyParticipant, initParticipantTimeline.

beforeEach(() => {
    jest.resetModules();
    globalThis.initScoreTimeline = jest.fn();
    require('./admin-participant-detail.js');
});

describe('resendInvite', () => {
    let fetchMock;

    beforeEach(() => {
        globalThis.confirm = jest.fn().mockReturnValue(true);
        globalThis.alert = jest.fn();
        fetchMock = jest.fn();
        globalThis.fetch = fetchMock;
    });

    test('returns early without fetch when user cancels confirm', () => {
        globalThis.confirm.mockReturnValue(false);

        const result = globalThis.resendInvite('p-1', 'csrf-token');

        expect(result).toBeUndefined();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    test('POSTs to resend-invite endpoint with csrf token', async () => {
        fetchMock.mockResolvedValue({
            json: () => Promise.resolve({ success: true }),
        });

        await globalThis.resendInvite('p-42', 'csrf-xyz');

        expect(fetchMock).toHaveBeenCalledWith(
            '/ctf/api/participants/p-42/resend-invite/',
            {
                method: 'POST',
                headers: {
                    'X-CSRFToken': 'csrf-xyz',
                    'Content-Type': 'application/json',
                },
            },
        );
        expect(globalThis.alert).toHaveBeenCalledWith('Invitation resent successfully.');
    });

    test('alerts the error message when the API reports failure', async () => {
        fetchMock.mockResolvedValue({
            json: () => Promise.resolve({ success: false, error: 'rate limited' }),
        });

        await globalThis.resendInvite('p-9', 'csrf');

        expect(globalThis.alert).toHaveBeenCalledWith('Error: rate limited');
        expect(globalThis.alert).not.toHaveBeenCalledWith('Invitation resent successfully.');
    });

    test('falls back to a default error message when no error field is returned', async () => {
        fetchMock.mockResolvedValue({
            json: () => Promise.resolve({ success: false }),
        });

        await globalThis.resendInvite('p-9', 'csrf');

        expect(globalThis.alert).toHaveBeenCalledWith('Error: Failed to resend invite');
    });

    test('alerts on network rejection', async () => {
        fetchMock.mockRejectedValue(new Error('network down'));

        await globalThis.resendInvite('p-9', 'csrf');

        expect(globalThis.alert).toHaveBeenCalledWith('Error resending invite: network down');
    });
});

describe('disqualifyParticipant', () => {
    beforeEach(() => {
        globalThis.confirm = jest.fn();
        globalThis.alert = jest.fn();
    });

    test('returns early without alert when user cancels confirm', () => {
        globalThis.confirm.mockReturnValue(false);

        const result = globalThis.disqualifyParticipant('p-1');

        expect(result).toBeUndefined();
        expect(globalThis.alert).not.toHaveBeenCalled();
    });

    test('shows the not-implemented alert when user confirms', () => {
        globalThis.confirm.mockReturnValue(true);

        globalThis.disqualifyParticipant('p-1');

        expect(globalThis.alert).toHaveBeenCalledWith(
            'Disqualify functionality not yet implemented via API.',
        );
    });
});

describe('initParticipantTimeline', () => {
    test('calls initScoreTimeline with the chart element id and participant score-timeline URL', () => {
        globalThis.initParticipantTimeline('p-42');

        expect(globalThis.initScoreTimeline).toHaveBeenCalledWith(
            'score-timeline-chart',
            '/ctf/api/participants/p-42/score-timeline/',
        );
    });
});
