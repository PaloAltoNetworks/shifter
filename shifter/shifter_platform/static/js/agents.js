/* global DirectUploader */
// Agent upload page: wire the upload form to the DirectUploader from
// upload.js. Extracted from the inline <script> in
// templates/mission_control/agents.html so the template stays within
// Sonar Web:LongJavaScriptCheck limits. Behavior is unchanged; the
// initiate/complete/cancel endpoints are read from the #upload-form
// element's data-* attributes and the CSRF token from the form's
// hidden csrfmiddlewaretoken field.

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('upload-form');
    const fileInput = document.getElementById('agent-file');
    const nameInput = document.getElementById('agent-name');
    const agentTypeInput = document.getElementById('agent-type');
    const progressContainer = document.getElementById('upload-progress');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const cancelBtn = document.getElementById('cancel-btn');
    const uploadBtn = document.getElementById('upload-btn');
    const errorDiv = document.getElementById('upload-error');

    let uploader = null;

    // Get CSRF token
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    form.addEventListener('submit', function (e) {
        e.preventDefault();

        const file = fileInput.files[0];
        const agentName = nameInput.value.trim();
        const agentType = agentTypeInput.value;

        if (!file || !agentName) {
            showError('Please provide both a name and file.');
            return;
        }

        // Create uploader instance
        uploader = new DirectUploader({
            initiateUrl: form.dataset.initiateUrl,
            completeUrl: form.dataset.completeUrl,
            cancelUrl: form.dataset.cancelUrl,
            csrfToken: csrfToken,
            maxSizeMB: 2048,

            onProgress: function (percent, message) {
                progressBar.style.width = percent + '%';
                progressText.textContent = message;
            },

            onSuccess: function (_result) {
                // Reload page to show new agent
                globalThis.location.reload();
            },

            onError: function (message) {
                showError(message);
                resetForm();
            },

            onCancel: function () {
                resetForm();
            }
        });

        // Show progress UI
        form.classList.add('uploading');
        progressContainer.classList.add('active');
        errorDiv.classList.remove('visible');
        progressBar.classList.remove('error');
        uploadBtn.textContent = 'Uploading...';

        // Start upload with agent type
        uploader.upload(file, agentName, agentType);
    });

    cancelBtn.addEventListener('click', function () {
        if (uploader) {
            uploader.cancel();
        }
    });

    function showError(message) {
        errorDiv.textContent = message;
        errorDiv.classList.add('visible');
        progressBar.classList.add('error');
    }

    function resetForm() {
        form.classList.remove('uploading');
        progressContainer.classList.remove('active');
        progressBar.style.width = '0%';
        progressBar.classList.remove('error');
        uploadBtn.textContent = 'Upload Agent';
        uploader = null;
    }
});
