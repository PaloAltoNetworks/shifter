// Tests for the scenario YAML editor: Tab soft-indent wiring (both the
// already-loaded init path and the DOMContentLoaded path) and async validation
// against the validate endpoint (valid, invalid-with-errors, and error paths).

function setupDom() {
    document.body.innerHTML =
        '<form>' +
        '<input type="hidden" name="csrfmiddlewaretoken" value="tok123">' +
        '<textarea id="yamlEditor"></textarea>' +
        '<div id="validationResult" style="display:none;" data-validate-url="/scenario/validate"></div>' +
        '</form>';
}

// Re-require against the current DOM. With readyState 'complete' (the jsdom
// default) the module calls initYamlEditor() immediately, wiring the keydown
// handler to the freshly built editor without registering a document listener.
function loadModule() {
    jest.resetModules();
    require('./yaml_editor.js');
}

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('yaml_editor', () => {
    beforeEach(() => {
        setupDom();
        globalThis.fetch = jest.fn();
        loadModule();
    });

    describe('initYamlEditor (Tab soft-indent)', () => {
        test('inserts two spaces at the caret and suppresses the default tab', () => {
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
            const editor = document.getElementById('yamlEditor');
            editor.value = 'ab';
            editor.selectionStart = editor.selectionEnd = 1;

            const evt = new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true });
            editor.dispatchEvent(evt);

            expect(editor.value).toBe('ab');
            expect(evt.defaultPrevented).toBe(false);
        });

        test('no-ops when the editor element is absent', () => {
            document.body.innerHTML = '';
            expect(() => loadModule()).not.toThrow();
        });

        test('wires the editor via DOMContentLoaded when the document is still loading', () => {
            setupDom();
            Object.defineProperty(document, 'readyState', { configurable: true, value: 'loading' });
            loadModule();
            document.dispatchEvent(new Event('DOMContentLoaded'));
            Object.defineProperty(document, 'readyState', { configurable: true, value: 'complete' });

            const editor = document.getElementById('yamlEditor');
            editor.value = 'ab';
            editor.selectionStart = editor.selectionEnd = 1;
            editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));

            expect(editor.value).toBe('a  b');
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
    });
});
