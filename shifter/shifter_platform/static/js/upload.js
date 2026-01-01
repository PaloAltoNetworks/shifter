/**
 * DirectUploader - Handles presigned URL uploads with progress tracking
 *
 * Flow:
 * 1. POST /api/upload/initiate/ - Get presigned URL
 * 2. PUT presigned URL - Upload file directly to S3
 * 3. POST /api/upload/complete/ - Create DB record
 */
class DirectUploader {
    constructor(options) {
        this.initiateUrl = options.initiateUrl;
        this.completeUrl = options.completeUrl;
        this.cancelUrl = options.cancelUrl;
        this.csrfToken = options.csrfToken;
        this.maxSizeMB = options.maxSizeMB || 2048;

        // Callbacks
        this.onProgress = options.onProgress || (() => {});
        this.onSuccess = options.onSuccess || (() => {});
        this.onError = options.onError || (() => {});
        this.onCancel = options.onCancel || (() => {});

        // State
        this.uploadToken = null;
        this.xhr = null;
        this.cancelled = false;
        this._boundBeforeUnload = null;
    }

    /**
     * Register beforeunload handler to cancel upload on page navigation
     */
    _registerBeforeUnload() {
        this._boundBeforeUnload = () => {
            if (this.uploadToken && !this.cancelled) {
                // Use sendBeacon for reliable delivery during page unload
                const data = JSON.stringify({ upload_token: this.uploadToken });
                navigator.sendBeacon(this.cancelUrl, new Blob([data], { type: 'application/json' }));
            }
        };
        window.addEventListener('beforeunload', this._boundBeforeUnload);
    }

    /**
     * Remove beforeunload handler
     */
    _unregisterBeforeUnload() {
        if (this._boundBeforeUnload) {
            window.removeEventListener('beforeunload', this._boundBeforeUnload);
            this._boundBeforeUnload = null;
        }
    }

    /**
     * Start upload process
     * @param {File} file - File object to upload
     * @param {string} agentName - User-provided name for the agent
     */
    async upload(file, agentName) {
        this.cancelled = false;
        this._registerBeforeUnload();

        // Validate file size
        const maxBytes = this.maxSizeMB * 1024 * 1024;
        if (file.size > maxBytes) {
            this.onError(`File size (${(file.size / 1024 / 1024).toFixed(1)} MB) exceeds maximum (${this.maxSizeMB} MB)`);
            return;
        }

        try {
            // Step 1: Get presigned URL
            this.onProgress(0, 'Preparing upload...');
            const initResponse = await this._initiateUpload(file, agentName);

            if (this.cancelled) return;

            this.uploadToken = initResponse.upload_token;

            // Step 2: Upload to S3
            this.onProgress(0, 'Uploading...');
            await this._uploadToS3(initResponse.presigned_url, file);

            if (this.cancelled) return;

            // Step 3: Complete upload
            this.onProgress(100, 'Finalizing...');
            const result = await this._completeUpload();

            this._unregisterBeforeUnload();
            this.onProgress(100, 'Complete');
            this.onSuccess(result);

        } catch (error) {
            this._unregisterBeforeUnload();
            if (!this.cancelled) {
                this.onError(error.message || 'Upload failed');
                // Try to cancel/cleanup on error
                this._cancelUpload();
            }
        }
    }

    /**
     * Cancel in-progress upload
     */
    cancel() {
        this.cancelled = true;
        this._unregisterBeforeUnload();

        if (this.xhr) {
            this.xhr.abort();
        }

        this._cancelUpload();
        this.onCancel();
    }

    async _initiateUpload(file, agentName) {
        const response = await fetch(this.initiateUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken,
            },
            body: JSON.stringify({
                name: agentName,
                filename: file.name,
                file_size: file.size,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to initiate upload');
        }

        return data;
    }

    _uploadToS3(presignedUrl, file) {
        return new Promise((resolve, reject) => {
            this.xhr = new XMLHttpRequest();

            // Progress tracking
            this.xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    const loadedMB = (e.loaded / 1024 / 1024).toFixed(1);
                    const totalMB = (e.total / 1024 / 1024).toFixed(1);
                    this.onProgress(percent, `Uploading... ${percent}% (${loadedMB} / ${totalMB} MB)`);
                }
            });

            this.xhr.addEventListener('load', () => {
                if (this.xhr.status >= 200 && this.xhr.status < 300) {
                    resolve();
                } else {
                    reject(new Error(`Upload failed with status ${this.xhr.status}`));
                }
            });

            this.xhr.addEventListener('error', () => {
                reject(new Error('Network error during upload'));
            });

            this.xhr.addEventListener('abort', () => {
                reject(new Error('Upload cancelled'));
            });

            this.xhr.open('PUT', presignedUrl);
            this.xhr.setRequestHeader('Content-Type', 'application/octet-stream');
            this.xhr.send(file);
        });
    }

    async _completeUpload() {
        const response = await fetch(this.completeUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken,
            },
            body: JSON.stringify({
                upload_token: this.uploadToken,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to complete upload');
        }

        return data;
    }

    async _cancelUpload() {
        if (!this.uploadToken) return;

        try {
            await fetch(this.cancelUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({
                    upload_token: this.uploadToken,
                }),
            });
        } catch {
            // Ignore cancel errors
        }
    }
}

// Export for use in templates
window.DirectUploader = DirectUploader;
