// Tests for the scenario editor "Create from YAML" page: the Tab soft-indent
// wiring registered on DOMContentLoaded and the async validation flow against
// the validate endpoint (valid, invalid-with-errors, and network-error paths,
// plus the missing-CSRF-field fallback).

// Required once so the single DOMContentLoaded listener is registered once;
// re-requiring would accumulate document-level listeners.
require('./scenario-yaml-create.js');

function setupDom() {
    document.body.innerHTML =
        '<form>' +
        '<input type="hidden" name="csrfmiddlewaretoken" value="tok123">' +
        '<textarea id="yamlEditor" data-validate-url="/scenario/validate"></textarea>' +
        '<div id="validationResult" style="display:none;"></div>' +
        '</form>';
}

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('scenario-yaml-create', () => {
    beforeEach(() => {
        setupDom();
        globalThis.fetch = jest.fn();
    });

    describe('Tab soft-indent (DOMContentLoaded wiring)', () => {
        test('inserts two spaces at the caret and suppresses the default tab', () => {
            document.dispatchEvent(new Event('DOMContentLoaded'));
            const editor = document.getElementById('yamlEditor');
            editor.value = 'ab';
            editor.selectionStart = editor.selectionEnd = 1;

            const evt = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
            editor.dispatchEvent(evt);

            expect(editor.value).toBe('a  b');
            expect(editor.selectionStart).toBe(3);
            expect(editor.selectionEnd).toBe(3);
            expect(evt.defaultPrevented).toBe(true);
        });

        test('leaves the value unchanged for non-Tab keys', () => {
            document.dispatchEvent(new Event('DOMContentLoaded'));
            const editor = document.getElementById('yamlEditor');
            editor.value = 'ab';
            editor.selectionStart = editor.selectionEnd = 1;

            const evt = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
            editor.dispatchEvent(evt);

            expect(editor.value).toBe('ab');
            expect(evt.defaultPrevented).toBe(false);
        });

        test('no-ops when the editor element is absent', () => {
            document.body.innerHTML = '';
            expect(() => document.dispatchEvent(new Event('DOMContentLoaded'))).not.toThrow();
        });
    });

    describe('validateYAML', () => {
        test('POSTs to the validate endpoint with the CSRF token and YAML body', async () => {
            document.getElementById('yamlEditor').value = 'name: demo';
            globalThis.fetch.mockResolvedValue({ json: () => Promise.resolve({ valid: true }) });

            globalThis.validateYAML();
            await flush();

            expect(globalThis.fetch).toHaveBeenCalledWith('/scenario/validate', expect.objectContaining({
                method: 'POST',
                headers: expect.objectContaining({
                    'Content-Type': 'application/json',
                    'X-CSRFToken': 'tok123',
                }),
                body: JSON.stringify({ yaml_content: 'name: demo' }),
            }));
        });

        test('shows the success message for a valid document', async () => {
            globalThis.fetch.mockResolvedValue({ json: () => Promise.resolve({ valid: true }) });

            globalThis.validateYAML();
            await flush();

            const result = document.getElementById('validationResult');
            expect(result.style.display).toBe('block');
            expect(result.className).toBe('validation-result validation-valid');
            expect(result.textContent).toBe('Valid scenario definition.');
        });

        test('renders a bulleted list of validation errors for an invalid document', async () => {
            globalThis.fetch.mockResolvedValue({
                json: () => Promise.resolve({ valid: false, errors: ['bad indent', 'missing name'] }),
            });

            globalThis.validateYAML();
            await flush();

            const result = document.getElementById('validationResult');
            expect(result.className).toBe('validation-result validation-invalid');
            expect(result.querySelector('strong').textContent).toBe('Validation errors:');
            const items = result.querySelectorAll('li');
            expect(items.length).toBe(2);
            expect(items[0].textContent).toBe('bad indent');
            expect(items[1].textContent).toBe('missing name');
        });

        test('shows the caught error message when the request rejects', async () => {
            globalThis.fetch.mockRejectedValue(new Error('offline'));

            globalThis.validateYAML();
            await flush();

            const result = document.getElementById('validationResult');
            expect(result.style.display).toBe('block');
            expect(result.className).toBe('validation-result validation-invalid');
            expect(result.textContent).toBe('Error validating: offline');
        });

        test('sends an empty CSRF token when the hidden field is absent', async () => {
            document.querySelector('[name=csrfmiddlewaretoken]').remove();
            globalThis.fetch.mockResolvedValue({ json: () => Promise.resolve({ valid: true }) });

            globalThis.validateYAML();
            await flush();

            expect(globalThis.fetch).toHaveBeenCalledWith('/scenario/validate', expect.objectContaining({
                headers: expect.objectContaining({ 'X-CSRFToken': '' }),
            }));
        });
    });
});
