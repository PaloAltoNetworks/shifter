// Tests for ctf-walkthrough.js — copyPrompt copies a step's <pre> text to the
// clipboard (whitespace-normalized) and flashes "Copied!" feedback that reverts
// after 2s.

require('./ctf-walkthrough.js');

describe('ctf-walkthrough copyPrompt', () => {
    let writeTextMock;

    beforeEach(() => {
        jest.useFakeTimers();
        document.body.innerHTML = `
            <div class="wt-prompt-block">
                <pre>  Run   this    command  </pre>
                <button id="copy-btn">Copy</button>
            </div>
        `;
        writeTextMock = jest.fn(() => Promise.resolve());
        Object.defineProperty(globalThis.navigator, 'clipboard', {
            configurable: true,
            value: { writeText: writeTextMock },
        });
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    test('exposes copyPrompt on globalThis', () => {
        expect(typeof globalThis.copyPrompt).toBe('function');
    });

    test('copies whitespace-normalized prompt text to the clipboard', () => {
        const btn = document.getElementById('copy-btn');

        globalThis.copyPrompt(btn);

        expect(writeTextMock).toHaveBeenCalledWith('Run this command');
    });

    test('shows Copied! feedback then reverts to Copy after 2s', async () => {
        const btn = document.getElementById('copy-btn');

        globalThis.copyPrompt(btn);
        // Flush the resolved clipboard promise's .then callback.
        await Promise.resolve();

        expect(btn.textContent).toBe('Copied!');
        expect(btn.classList.contains('copied')).toBe(true);

        jest.advanceTimersByTime(2000);

        expect(btn.textContent).toBe('Copy');
        expect(btn.classList.contains('copied')).toBe(false);
    });
});
