/**
 * Agent upload page tests.
 *
 * The module wires the #upload-form to a DirectUploader (global from upload.js).
 * We mock DirectUploader so we can capture the options object and drive its
 * progress/success/error/cancel callbacks, and assert the form/progress UI
 * effects. Endpoint URLs come from the form's data-* attributes and the CSRF
 * token from the hidden csrfmiddlewaretoken field.
 */

require('./agents.js');

const buildMarkup = () => `
    <form id="upload-form"
          data-initiate-url="/init"
          data-complete-url="/complete"
          data-cancel-url="/cancel">
        <input type="hidden" name="csrfmiddlewaretoken" value="csrf-token">
        <input type="file" id="agent-file">
        <input type="text" id="agent-name">
        <select id="agent-type"><option value="python" selected>python</option></select>
        <div id="upload-progress"></div>
        <div id="progress-bar"></div>
        <div id="progress-text"></div>
        <button type="button" id="cancel-btn">Cancel</button>
        <button type="submit" id="upload-btn">Upload Agent</button>
        <div id="upload-error"></div>
    </form>
`;

function setFile(name) {
    const fileInput = document.getElementById('agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: name ? [{ name }] : [],
    });
}

function submitForm() {
    document
        .getElementById('upload-form')
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
}

describe('agents upload page', () => {
    let capturedOpts;
    let uploadMock;
    let cancelMock;

    beforeEach(() => {
        jest.spyOn(console, 'error').mockImplementation(() => {});
        document.body.innerHTML = buildMarkup();

        capturedOpts = null;
        uploadMock = jest.fn();
        cancelMock = jest.fn();
        globalThis.DirectUploader = jest.fn(function (opts) {
            capturedOpts = opts;
            this.upload = uploadMock;
            this.cancel = cancelMock;
        });

        document.dispatchEvent(new Event('DOMContentLoaded'));
    });

    afterEach(() => {
        jest.restoreAllMocks();
    });

    test('shows an error and skips the uploader when name or file is missing', () => {
        setFile(null);
        document.getElementById('agent-name').value = '';

        submitForm();

        expect(globalThis.DirectUploader).not.toHaveBeenCalled();
        const err = document.getElementById('upload-error');
        expect(err.textContent).toBe('Please provide both a name and file.');
        expect(err.classList.contains('visible')).toBe(true);
        expect(document.getElementById('progress-bar').classList.contains('error')).toBe(true);
    });

    test('creates the uploader and starts the upload for a valid submission', () => {
        setFile('agent.zip');
        document.getElementById('agent-name').value = '  My Agent  ';
        document.getElementById('agent-type').value = 'python';

        submitForm();

        expect(globalThis.DirectUploader).toHaveBeenCalledTimes(1);
        expect(capturedOpts).toMatchObject({
            initiateUrl: '/init',
            completeUrl: '/complete',
            cancelUrl: '/cancel',
            csrfToken: 'csrf-token',
            maxSizeMB: 2048,
        });
        expect(uploadMock).toHaveBeenCalledWith({ name: 'agent.zip' }, 'My Agent', 'python');
        expect(document.getElementById('upload-form').classList.contains('uploading')).toBe(true);
        expect(document.getElementById('upload-progress').classList.contains('active')).toBe(true);
        expect(document.getElementById('upload-btn').textContent).toBe('Uploading...');
    });

    test('uploader callbacks drive progress, success, error, and cancel UI', () => {
        setFile('agent.zip');
        document.getElementById('agent-name').value = 'Agent';
        submitForm();

        // onProgress updates the bar width and text.
        capturedOpts.onProgress(42, 'Uploading chunk');
        expect(document.getElementById('progress-bar').style.width).toBe('42%');
        expect(document.getElementById('progress-text').textContent).toBe('Uploading chunk');

        // onSuccess reloads the page (jsdom no-op; must not throw).
        expect(() => capturedOpts.onSuccess({ id: 1 })).not.toThrow();

        // onError shows the message and resets the form.
        capturedOpts.onError('boom');
        expect(document.getElementById('upload-error').textContent).toBe('boom');
        expect(document.getElementById('upload-form').classList.contains('uploading')).toBe(false);
        expect(document.getElementById('progress-bar').style.width).toBe('0%');
        expect(document.getElementById('upload-btn').textContent).toBe('Upload Agent');

        // onCancel resets the form.
        document.getElementById('upload-form').classList.add('uploading');
        capturedOpts.onCancel();
        expect(document.getElementById('upload-form').classList.contains('uploading')).toBe(false);
    });

    test('cancel button cancels an in-progress upload', () => {
        setFile('agent.zip');
        document.getElementById('agent-name').value = 'Agent';
        submitForm();

        document.getElementById('cancel-btn').click();

        expect(cancelMock).toHaveBeenCalledTimes(1);
    });

    test('cancel button is a no-op when no upload is in progress', () => {
        expect(() => document.getElementById('cancel-btn').click()).not.toThrow();
        expect(cancelMock).not.toHaveBeenCalled();
    });
});
