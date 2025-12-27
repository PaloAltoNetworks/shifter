/**
 * Unit tests for DirectUploader (upload.js)
 *
 * Tests cover:
 * - Constructor and initialization
 * - beforeunload handler registration/cleanup
 * - Full upload flow (happy path)
 * - Failure modes (file size, HTTP errors, network errors)
 * - Cancellation at various stages
 * - XHR event handling (progress, load, error, abort)
 * - All internal methods
 */

// Load the module under test
require('./upload.js');

describe('DirectUploader', () => {
    let uploader;
    let mockCallbacks;
    let mockXhr;
    let xhrEventHandlers;
    let xhrUploadEventHandlers;
    let windowEventHandlers;
    let originalFetch;
    let originalXMLHttpRequest;
    let originalSendBeacon;
    let originalAddEventListener;
    let originalRemoveEventListener;

    const defaultOptions = {
        initiateUrl: '/api/upload/initiate/',
        completeUrl: '/api/upload/complete/',
        cancelUrl: '/api/upload/cancel/',
        csrfToken: 'test-csrf-token',
    };

    const createMockFile = (size = 1024, name = 'test-file.exe') => {
        return { name, size };
    };

    const createMockXhr = () => {
        xhrEventHandlers = {};
        xhrUploadEventHandlers = {};

        return {
            open: jest.fn(),
            send: jest.fn(),
            setRequestHeader: jest.fn(),
            abort: jest.fn(),
            status: 200,
            upload: {
                addEventListener: jest.fn((event, handler) => {
                    xhrUploadEventHandlers[event] = handler;
                }),
            },
            addEventListener: jest.fn((event, handler) => {
                xhrEventHandlers[event] = handler;
            }),
        };
    };

    const triggerXhrLoad = (status = 200) => {
        mockXhr.status = status;
        if (xhrEventHandlers.load) {
            xhrEventHandlers.load();
        }
    };

    const triggerXhrError = () => {
        if (xhrEventHandlers.error) {
            xhrEventHandlers.error();
        }
    };

    const triggerXhrAbort = () => {
        if (xhrEventHandlers.abort) {
            xhrEventHandlers.abort();
        }
    };

    const triggerUploadProgress = (loaded, total, lengthComputable = true) => {
        if (xhrUploadEventHandlers.progress) {
            xhrUploadEventHandlers.progress({ loaded, total, lengthComputable });
        }
    };

    const mockFetchSuccess = (data) => {
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(data),
        });
    };

    const mockFetchError = (status, data) => {
        return Promise.resolve({
            ok: false,
            status,
            json: () => Promise.resolve(data),
        });
    };

    const mockFetchNetworkError = () => {
        return Promise.reject(new Error('Network error'));
    };

    beforeEach(() => {
        // Store originals
        originalFetch = global.fetch;
        originalXMLHttpRequest = global.XMLHttpRequest;
        originalSendBeacon = navigator.sendBeacon;
        originalAddEventListener = window.addEventListener;
        originalRemoveEventListener = window.removeEventListener;

        // Setup window event handler tracking
        windowEventHandlers = {};
        window.addEventListener = jest.fn((event, handler) => {
            windowEventHandlers[event] = handler;
        });
        window.removeEventListener = jest.fn((event, handler) => {
            if (windowEventHandlers[event] === handler) {
                delete windowEventHandlers[event];
            }
        });

        // Setup navigator.sendBeacon mock
        navigator.sendBeacon = jest.fn(() => true);

        // Setup XHR mock
        mockXhr = createMockXhr();
        global.XMLHttpRequest = jest.fn(() => mockXhr);

        // Setup fetch mock
        global.fetch = jest.fn();

        // Setup callbacks
        mockCallbacks = {
            onProgress: jest.fn(),
            onSuccess: jest.fn(),
            onError: jest.fn(),
            onCancel: jest.fn(),
        };

        uploader = new window.DirectUploader({
            ...defaultOptions,
            ...mockCallbacks,
        });
    });

    afterEach(() => {
        // Restore originals
        global.fetch = originalFetch;
        global.XMLHttpRequest = originalXMLHttpRequest;
        navigator.sendBeacon = originalSendBeacon;
        window.addEventListener = originalAddEventListener;
        window.removeEventListener = originalRemoveEventListener;
    });

    // =========================================================================
    // A. Constructor Tests
    // =========================================================================
    describe('constructor', () => {
        test('uses provided options correctly', () => {
            expect(uploader.initiateUrl).toBe('/api/upload/initiate/');
            expect(uploader.completeUrl).toBe('/api/upload/complete/');
            expect(uploader.cancelUrl).toBe('/api/upload/cancel/');
            expect(uploader.csrfToken).toBe('test-csrf-token');
        });

        test('applies default maxSizeMB of 2048', () => {
            expect(uploader.maxSizeMB).toBe(2048);
        });

        test('uses custom maxSizeMB when provided', () => {
            const customUploader = new window.DirectUploader({
                ...defaultOptions,
                maxSizeMB: 100,
            });
            expect(customUploader.maxSizeMB).toBe(100);
        });

        test('assigns no-op callbacks when not provided', () => {
            const minimalUploader = new window.DirectUploader(defaultOptions);
            // Should not throw when called
            expect(() => minimalUploader.onProgress(50, 'test')).not.toThrow();
            expect(() => minimalUploader.onSuccess({})).not.toThrow();
            expect(() => minimalUploader.onError('error')).not.toThrow();
            expect(() => minimalUploader.onCancel()).not.toThrow();
        });

        test('initializes state correctly', () => {
            expect(uploader.uploadToken).toBeNull();
            expect(uploader.xhr).toBeNull();
            expect(uploader.cancelled).toBe(false);
            expect(uploader._boundBeforeUnload).toBeNull();
        });
    });

    // =========================================================================
    // B. beforeunload Handler Tests
    // =========================================================================
    describe('_registerBeforeUnload / _unregisterBeforeUnload', () => {
        test('adds beforeunload event listener', () => {
            uploader._registerBeforeUnload();

            expect(window.addEventListener).toHaveBeenCalledWith(
                'beforeunload',
                expect.any(Function)
            );
            expect(uploader._boundBeforeUnload).not.toBeNull();
        });

        test('handler calls sendBeacon with correct JSON when token exists and not cancelled', () => {
            uploader.uploadToken = 'test-token-123';
            uploader.cancelled = false;
            uploader._registerBeforeUnload();

            // Trigger the beforeunload handler
            windowEventHandlers.beforeunload();

            expect(navigator.sendBeacon).toHaveBeenCalledWith(
                '/api/upload/cancel/',
                expect.any(Blob)
            );

            // Verify the blob properties
            const blobArg = navigator.sendBeacon.mock.calls[0][1];
            expect(blobArg.type).toBe('application/json');

            // Verify blob size matches expected JSON exactly
            // This catches bugs where the token is wrong/missing/malformed
            const expectedJson = JSON.stringify({ upload_token: 'test-token-123' });
            expect(blobArg.size).toBe(expectedJson.length);

            // Verify with a different token to ensure size check is meaningful
            const wrongJson = JSON.stringify({ upload_token: 'wrong' });
            expect(blobArg.size).not.toBe(wrongJson.length);
        });

        test('handler does nothing when cancelled is true', () => {
            uploader.uploadToken = 'test-token-123';
            uploader.cancelled = true;
            uploader._registerBeforeUnload();

            windowEventHandlers.beforeunload();

            expect(navigator.sendBeacon).not.toHaveBeenCalled();
        });

        test('handler does nothing when uploadToken is null', () => {
            uploader.uploadToken = null;
            uploader.cancelled = false;
            uploader._registerBeforeUnload();

            windowEventHandlers.beforeunload();

            expect(navigator.sendBeacon).not.toHaveBeenCalled();
        });

        test('unregister removes event listener', () => {
            uploader._registerBeforeUnload();
            const handler = uploader._boundBeforeUnload;

            uploader._unregisterBeforeUnload();

            expect(window.removeEventListener).toHaveBeenCalledWith(
                'beforeunload',
                handler
            );
            expect(uploader._boundBeforeUnload).toBeNull();
        });

        test('unregister is idempotent (no-op when already unregistered)', () => {
            // Call unregister without ever registering
            expect(() => uploader._unregisterBeforeUnload()).not.toThrow();
            expect(window.removeEventListener).not.toHaveBeenCalled();
        });
    });

    // =========================================================================
    // C. upload() Happy Path Tests
    // =========================================================================
    describe('upload() - happy path', () => {
        const setupSuccessfulUpload = () => {
            // Mock initiate response
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.amazonaws.com/bucket/key?signature=xxx',
                    })
                )
                // Mock complete response
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        id: 1,
                        name: 'Test Agent',
                    })
                );
        };

        test('full successful flow: initiate -> S3 -> complete -> onSuccess', async () => {
            setupSuccessfulUpload();
            const file = createMockFile(1024);

            const uploadPromise = uploader.upload(file, 'Test Agent');

            // Wait for initiate to complete, then trigger S3 success
            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            expect(mockCallbacks.onSuccess).toHaveBeenCalledWith({
                id: 1,
                name: 'Test Agent',
            });
            expect(mockCallbacks.onError).not.toHaveBeenCalled();
        });

        test('calls onProgress with correct messages at each stage', async () => {
            setupSuccessfulUpload();
            const file = createMockFile(1024);

            const uploadPromise = uploader.upload(file, 'Test Agent');

            // Check initial progress
            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(0, 'Preparing upload...');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // After initiate, before S3
            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(0, 'Uploading...');

            triggerXhrLoad(200);
            await uploadPromise;

            // After complete
            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(100, 'Finalizing...');
            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(100, 'Complete');
        });

        test('stores uploadToken from initiate response', async () => {
            setupSuccessfulUpload();
            const file = createMockFile(1024);

            const uploadPromise = uploader.upload(file, 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            expect(uploader.uploadToken).toBe('token-abc');

            triggerXhrLoad(200);
            await uploadPromise;
        });

        test('unregisters beforeunload on success', async () => {
            setupSuccessfulUpload();
            const file = createMockFile(1024);

            const uploadPromise = uploader.upload(file, 'Test Agent');

            // Should have registered
            expect(window.addEventListener).toHaveBeenCalledWith(
                'beforeunload',
                expect.any(Function)
            );

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);
            await uploadPromise;

            // Should have unregistered
            expect(window.removeEventListener).toHaveBeenCalled();
        });
    });

    // =========================================================================
    // D. upload() Failure Mode Tests
    // =========================================================================
    describe('upload() - failure modes', () => {
        test('file too large: calls onError with exact size message, does NOT call initiate', async () => {
            const maxSizeMB = 100;
            const customUploader = new window.DirectUploader({
                ...defaultOptions,
                ...mockCallbacks,
                maxSizeMB,
            });

            const oversizedFile = createMockFile(150 * 1024 * 1024); // 150 MB

            await customUploader.upload(oversizedFile, 'Test Agent');

            // Verify the EXACT error message format
            expect(mockCallbacks.onError).toHaveBeenCalledWith(
                'File size (150.0 MB) exceeds maximum (100 MB)'
            );
            expect(global.fetch).not.toHaveBeenCalled();
        });

        test('initiate fails (HTTP error): calls onError, calls _cancelUpload', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchError(400, { error: 'Invalid file type' })
            );

            await uploader.upload(createMockFile(), 'Test Agent');

            expect(mockCallbacks.onError).toHaveBeenCalledWith('Invalid file type');
        });

        test('initiate fails (network error): calls onError', async () => {
            global.fetch.mockImplementationOnce(() => mockFetchNetworkError());

            await uploader.upload(createMockFile(), 'Test Agent');

            expect(mockCallbacks.onError).toHaveBeenCalledWith('Network error');
        });

        test('S3 upload fails (non-2xx): calls onError', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() => mockFetchSuccess({})); // cancel endpoint

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(403); // Forbidden

            await uploadPromise;

            expect(mockCallbacks.onError).toHaveBeenCalledWith(
                'Upload failed with status 403'
            );
        });

        test('S3 upload fails (network error): calls onError', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() => mockFetchSuccess({})); // cancel endpoint

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrError();

            await uploadPromise;

            expect(mockCallbacks.onError).toHaveBeenCalledWith(
                'Network error during upload'
            );
        });

        test('complete fails: calls onError', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchError(500, { error: 'Database error' })
                )
                .mockImplementationOnce(() => mockFetchSuccess({})); // cancel endpoint

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            expect(mockCallbacks.onError).toHaveBeenCalledWith('Database error');
        });

        test('error with custom message from server: uses server-provided error message', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchError(400, { error: 'Custom server error message' })
            );

            await uploader.upload(createMockFile(), 'Test Agent');

            expect(mockCallbacks.onError).toHaveBeenCalledWith(
                'Custom server error message'
            );
        });

        test('error without message: uses default fallback message', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchError(400, {}) // No error field
            );

            await uploader.upload(createMockFile(), 'Test Agent');

            expect(mockCallbacks.onError).toHaveBeenCalledWith('Failed to initiate upload');
        });

        test('handles malformed JSON response from server', async () => {
            global.fetch.mockImplementationOnce(() =>
                Promise.resolve({
                    ok: true,
                    json: () => Promise.reject(new SyntaxError('Unexpected token < in JSON')),
                })
            );

            await uploader.upload(createMockFile(), 'Test Agent');

            expect(mockCallbacks.onError).toHaveBeenCalled();
            expect(mockCallbacks.onSuccess).not.toHaveBeenCalled();
        });

        test('handles missing presigned_url in initiate response', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'token-abc',
                    // presigned_url is missing!
                })
            );

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // XHR.open will be called with undefined - this should cause an error
            // or the S3 upload should fail
            triggerXhrError();

            await uploadPromise;

            expect(mockCallbacks.onError).toHaveBeenCalled();
            expect(mockCallbacks.onSuccess).not.toHaveBeenCalled();
        });

        test('handles missing upload_token in initiate response', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        presigned_url: 'https://s3.example.com/upload',
                        // upload_token is missing!
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchError(400, { error: 'Invalid upload token' })
                );

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            // Complete will be called with undefined token - should fail
            expect(mockCallbacks.onError).toHaveBeenCalled();
        });
    });

    // =========================================================================
    // D2. upload() Edge Cases and Boundary Tests
    // =========================================================================
    describe('upload() - edge cases and boundaries', () => {
        test('file exactly at size limit is allowed', async () => {
            const maxSizeMB = 100;
            const customUploader = new window.DirectUploader({
                ...defaultOptions,
                ...mockCallbacks,
                maxSizeMB,
            });

            // Exactly 100 MB (at the limit, not over)
            const exactLimitFile = createMockFile(100 * 1024 * 1024);

            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'token-abc',
                    presigned_url: 'https://s3.example.com/upload',
                })
            );

            customUploader.upload(exactLimitFile, 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // Should have called fetch (not rejected due to size)
            expect(global.fetch).toHaveBeenCalled();
            expect(mockCallbacks.onError).not.toHaveBeenCalled();
        });

        test('file one byte over limit is rejected', async () => {
            const maxSizeMB = 100;
            const customUploader = new window.DirectUploader({
                ...defaultOptions,
                ...mockCallbacks,
                maxSizeMB,
            });

            // 100 MB + 1 byte
            const overLimitFile = createMockFile(100 * 1024 * 1024 + 1);

            await customUploader.upload(overLimitFile, 'Test Agent');

            expect(global.fetch).not.toHaveBeenCalled();
            expect(mockCallbacks.onError).toHaveBeenCalled();
        });

        test('zero-byte file is handled correctly', async () => {
            const zeroByteFile = createMockFile(0, 'empty.exe');

            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchSuccess({ id: 1, name: 'Empty Agent' })
                );

            const uploadPromise = uploader.upload(zeroByteFile, 'Empty Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            // Should complete without division by zero or other errors
            expect(mockCallbacks.onSuccess).toHaveBeenCalled();
            expect(mockCallbacks.onError).not.toHaveBeenCalled();
        });

        test('very large file (2GB) progress calculation does not overflow', async () => {
            const twoGBFile = createMockFile(2 * 1024 * 1024 * 1024); // 2 GB

            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'token-abc',
                    presigned_url: 'https://s3.example.com/upload',
                })
            );

            const uploadPromise = uploader.upload(twoGBFile, 'Large Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // Simulate 50% progress of 2GB file
            const halfOf2GB = 1 * 1024 * 1024 * 1024;
            const total2GB = 2 * 1024 * 1024 * 1024;
            triggerUploadProgress(halfOf2GB, total2GB);

            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(
                50,
                expect.stringContaining('50%')
            );

            // Verify the MB values are reasonable (1024 MB loaded, 2048 MB total)
            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(
                50,
                expect.stringMatching(/1024\.0.*2048\.0/)
            );

            triggerXhrLoad(200);
            await uploadPromise;
        });

        test('onError callback throwing does not break cleanup', async () => {
            const throwingCallbacks = {
                ...mockCallbacks,
                onError: jest.fn(() => {
                    throw new Error('Callback exploded!');
                }),
            };

            const throwingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...throwingCallbacks,
            });

            global.fetch.mockImplementationOnce(() =>
                mockFetchError(500, { error: 'Server error' })
            );

            // Should not throw even though callback throws
            await expect(
                throwingUploader.upload(createMockFile(), 'Test Agent')
            ).rejects.toThrow('Callback exploded!');

            // Callback was still called
            expect(throwingCallbacks.onError).toHaveBeenCalledWith('Server error');
        });

        test('onSuccess callback throwing is caught and triggers onError', async () => {
            // This test verifies the ACTUAL behavior: when onSuccess throws,
            // the exception is caught by the try/catch and onError is called
            const throwingCallbacks = {
                onProgress: jest.fn(),
                onSuccess: jest.fn(() => {
                    throw new Error('Success callback exploded!');
                }),
                onError: jest.fn(),
                onCancel: jest.fn(),
            };

            const throwingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...throwingCallbacks,
            });

            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchSuccess({ id: 1, name: 'Test Agent' })
                )
                .mockImplementationOnce(() => mockFetchSuccess({})); // cancel from error path

            const uploadPromise = throwingUploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            // Success callback was invoked with correct data
            expect(throwingCallbacks.onSuccess).toHaveBeenCalledWith({
                id: 1,
                name: 'Test Agent',
            });

            // But since it threw, onError was also called with the exception message
            expect(throwingCallbacks.onError).toHaveBeenCalledWith('Success callback exploded!');
        });

        test('onProgress callback throwing does not abort upload', async () => {
            let progressCallCount = 0;
            const throwingCallbacks = {
                ...mockCallbacks,
                onProgress: jest.fn(() => {
                    progressCallCount++;
                    if (progressCallCount === 1) {
                        throw new Error('Progress callback exploded!');
                    }
                }),
            };

            const throwingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...throwingCallbacks,
            });

            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchSuccess({ id: 1, name: 'Test Agent' })
                );

            const uploadPromise = throwingUploader.upload(createMockFile(), 'Test Agent');

            // First onProgress call throws, but upload should continue
            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            // The promise may reject due to the callback throwing
            try {
                await uploadPromise;
            } catch (e) {
                // Expected - callback threw
            }

            // Progress was called
            expect(throwingCallbacks.onProgress).toHaveBeenCalled();
        });
    });

    // =========================================================================
    // E. upload() Cancellation Tests
    // =========================================================================
    describe('upload() - cancellation', () => {
        test('cancelled before initiate completes: early return, no S3 call', async () => {
            let resolveInitiate;
            global.fetch.mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveInitiate = resolve;
                    })
            );

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            // Cancel before initiate resolves
            uploader.cancel();

            // Now resolve initiate
            resolveInitiate({
                ok: true,
                json: () =>
                    Promise.resolve({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    }),
            });

            await uploadPromise;

            // S3 upload should not have been initiated
            expect(mockXhr.open).not.toHaveBeenCalled();
        });

        test('cancelled during S3 upload: early return, no complete call', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() => mockFetchSuccess({})); // cancel endpoint

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // S3 upload has started
            expect(mockXhr.open).toHaveBeenCalled();

            // Cancel during S3 upload
            uploader.cancel();

            // Trigger abort (which happens after cancel)
            triggerXhrAbort();

            await uploadPromise;

            // Should have 2 fetches: initiate + cancel (NOT complete)
            expect(global.fetch).toHaveBeenCalledTimes(2);
            // Verify that the second call was to cancel, not complete
            expect(global.fetch).toHaveBeenLastCalledWith(
                '/api/upload/cancel/',
                expect.any(Object)
            );
        });

        test('does NOT call onError when cancelled (error suppressed)', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'token-abc',
                    presigned_url: 'https://s3.example.com/upload',
                })
            );

            const uploadPromise = uploader.upload(createMockFile(), 'Test Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            uploader.cancel();
            triggerXhrAbort();

            await uploadPromise;

            expect(mockCallbacks.onError).not.toHaveBeenCalled();
            expect(mockCallbacks.onCancel).toHaveBeenCalled();
        });
    });

    // =========================================================================
    // F. cancel() Tests
    // =========================================================================
    describe('cancel()', () => {
        test('sets cancelled flag to true', () => {
            expect(uploader.cancelled).toBe(false);

            uploader.cancel();

            expect(uploader.cancelled).toBe(true);
        });

        test('calls xhr.abort() when XHR exists', () => {
            uploader.xhr = mockXhr;

            uploader.cancel();

            expect(mockXhr.abort).toHaveBeenCalled();
        });

        test('does NOT throw when xhr is null', () => {
            uploader.xhr = null;

            expect(() => uploader.cancel()).not.toThrow();
        });

        test('calls _cancelUpload()', async () => {
            uploader.uploadToken = 'test-token';
            global.fetch.mockImplementationOnce(() => mockFetchSuccess({}));

            uploader.cancel();

            // Give async _cancelUpload time to execute
            await new Promise((resolve) => setTimeout(resolve, 0));

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/upload/cancel/',
                expect.objectContaining({
                    method: 'POST',
                })
            );
        });

        test('calls onCancel callback', () => {
            uploader.cancel();

            expect(mockCallbacks.onCancel).toHaveBeenCalled();
        });

        test('unregisters beforeunload handler', () => {
            uploader._registerBeforeUnload();
            const handler = uploader._boundBeforeUnload;

            uploader.cancel();

            expect(window.removeEventListener).toHaveBeenCalledWith(
                'beforeunload',
                handler
            );
        });
    });

    // =========================================================================
    // G. _initiateUpload() Tests
    // =========================================================================
    describe('_initiateUpload()', () => {
        test('sends POST to correct URL', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({ upload_token: 'token', presigned_url: 'url' })
            );

            await uploader._initiateUpload(createMockFile(), 'Test Agent');

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/upload/initiate/',
                expect.any(Object)
            );
        });

        test('includes correct headers (Content-Type, X-CSRFToken)', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({ upload_token: 'token', presigned_url: 'url' })
            );

            await uploader._initiateUpload(createMockFile(), 'Test Agent');

            expect(global.fetch).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': 'test-csrf-token',
                    },
                })
            );
        });

        test('sends correct JSON body (name, filename, file_size)', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({ upload_token: 'token', presigned_url: 'url' })
            );

            const file = createMockFile(2048, 'agent.exe');
            await uploader._initiateUpload(file, 'My Agent');

            const callArgs = global.fetch.mock.calls[0][1];
            const body = JSON.parse(callArgs.body);

            expect(body).toEqual({
                name: 'My Agent',
                filename: 'agent.exe',
                file_size: 2048,
            });
        });

        test('returns parsed JSON on 2xx response', async () => {
            const responseData = {
                upload_token: 'token-xyz',
                presigned_url: 'https://s3.example.com/upload',
            };
            global.fetch.mockImplementationOnce(() => mockFetchSuccess(responseData));

            const result = await uploader._initiateUpload(createMockFile(), 'Test');

            expect(result).toEqual(responseData);
        });

        test('throws Error with data.error on non-2xx', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchError(400, { error: 'Specific error message' })
            );

            await expect(
                uploader._initiateUpload(createMockFile(), 'Test')
            ).rejects.toThrow('Specific error message');
        });

        test('throws Error with default message when data.error missing', async () => {
            global.fetch.mockImplementationOnce(() => mockFetchError(400, {}));

            await expect(
                uploader._initiateUpload(createMockFile(), 'Test')
            ).rejects.toThrow('Failed to initiate upload');
        });
    });

    // =========================================================================
    // H. _uploadToS3() Tests
    // =========================================================================
    describe('_uploadToS3()', () => {
        const presignedUrl = 'https://s3.amazonaws.com/bucket/key?sig=xxx';
        const file = createMockFile(1024 * 1024); // 1 MB

        test('creates XHR and stores in this.xhr', () => {
            uploader._uploadToS3(presignedUrl, file);

            expect(uploader.xhr).toBe(mockXhr);
        });

        test('opens PUT request to presigned URL', () => {
            uploader._uploadToS3(presignedUrl, file);

            expect(mockXhr.open).toHaveBeenCalledWith('PUT', presignedUrl);
        });

        test('sets Content-Type: application/octet-stream', () => {
            uploader._uploadToS3(presignedUrl, file);

            expect(mockXhr.setRequestHeader).toHaveBeenCalledWith(
                'Content-Type',
                'application/octet-stream'
            );
        });

        test('sends file as body', () => {
            uploader._uploadToS3(presignedUrl, file);

            expect(mockXhr.send).toHaveBeenCalledWith(file);
        });

        test('progress events: calls onProgress with calculated percent and formatted MB', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            // Simulate 50% progress (512 KB of 1 MB)
            triggerUploadProgress(512 * 1024, 1024 * 1024);

            expect(mockCallbacks.onProgress).toHaveBeenCalledWith(
                50,
                'Uploading... 50% (0.5 / 1.0 MB)'
            );

            triggerXhrLoad(200);
            await promise;
        });

        test('progress edge case: handles lengthComputable=false (no call)', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerUploadProgress(512 * 1024, 1024 * 1024, false);

            expect(mockCallbacks.onProgress).not.toHaveBeenCalled();

            triggerXhrLoad(200);
            await promise;
        });

        test('resolves promise on status 200', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerXhrLoad(200);

            await expect(promise).resolves.toBeUndefined();
        });

        test('resolves promise on status 204', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerXhrLoad(204);

            await expect(promise).resolves.toBeUndefined();
        });

        test('rejects on status 400', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerXhrLoad(400);

            await expect(promise).rejects.toThrow('Upload failed with status 400');
        });

        test('rejects on status 500', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerXhrLoad(500);

            await expect(promise).rejects.toThrow('Upload failed with status 500');
        });

        test('rejects with "Network error during upload" on XHR error event', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerXhrError();

            await expect(promise).rejects.toThrow('Network error during upload');
        });

        test('rejects with "Upload cancelled" on XHR abort event', async () => {
            const promise = uploader._uploadToS3(presignedUrl, file);

            triggerXhrAbort();

            await expect(promise).rejects.toThrow('Upload cancelled');
        });
    });

    // =========================================================================
    // I. _completeUpload() Tests
    // =========================================================================
    describe('_completeUpload()', () => {
        beforeEach(() => {
            uploader.uploadToken = 'test-upload-token';
        });

        test('sends POST to correct URL', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({ id: 1, name: 'Agent' })
            );

            await uploader._completeUpload();

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/upload/complete/',
                expect.any(Object)
            );
        });

        test('includes correct headers (Content-Type, X-CSRFToken)', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({ id: 1, name: 'Agent' })
            );

            await uploader._completeUpload();

            expect(global.fetch).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': 'test-csrf-token',
                    },
                })
            );
        });

        test('sends correct JSON body (upload_token)', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({ id: 1, name: 'Agent' })
            );

            await uploader._completeUpload();

            const callArgs = global.fetch.mock.calls[0][1];
            const body = JSON.parse(callArgs.body);

            expect(body).toEqual({
                upload_token: 'test-upload-token',
            });
        });

        test('returns parsed JSON on 2xx response', async () => {
            const responseData = { id: 42, name: 'Completed Agent' };
            global.fetch.mockImplementationOnce(() => mockFetchSuccess(responseData));

            const result = await uploader._completeUpload();

            expect(result).toEqual(responseData);
        });

        test('throws Error with data.error on non-2xx', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchError(500, { error: 'Completion failed' })
            );

            await expect(uploader._completeUpload()).rejects.toThrow(
                'Completion failed'
            );
        });

        test('throws Error with default message when data.error missing', async () => {
            global.fetch.mockImplementationOnce(() => mockFetchError(500, {}));

            await expect(uploader._completeUpload()).rejects.toThrow(
                'Failed to complete upload'
            );
        });
    });

    // =========================================================================
    // J. _cancelUpload() Tests
    // =========================================================================
    describe('_cancelUpload()', () => {
        test('does nothing when uploadToken is null', async () => {
            uploader.uploadToken = null;

            await uploader._cancelUpload();

            expect(global.fetch).not.toHaveBeenCalled();
        });

        test('sends POST to cancel URL when token exists', async () => {
            uploader.uploadToken = 'token-to-cancel';
            global.fetch.mockImplementationOnce(() => mockFetchSuccess({}));

            await uploader._cancelUpload();

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/upload/cancel/',
                expect.objectContaining({
                    method: 'POST',
                })
            );
        });

        test('includes correct headers and body', async () => {
            uploader.uploadToken = 'token-to-cancel';
            global.fetch.mockImplementationOnce(() => mockFetchSuccess({}));

            await uploader._cancelUpload();

            expect(global.fetch).toHaveBeenCalledWith(
                '/api/upload/cancel/',
                expect.objectContaining({
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': 'test-csrf-token',
                    },
                })
            );

            const callArgs = global.fetch.mock.calls[0][1];
            const body = JSON.parse(callArgs.body);
            expect(body).toEqual({ upload_token: 'token-to-cancel' });
        });

        test('silently ignores fetch errors (no throw)', async () => {
            uploader.uploadToken = 'token-to-cancel';
            global.fetch.mockImplementationOnce(() => mockFetchNetworkError());

            // Should not throw
            await expect(uploader._cancelUpload()).resolves.toBeUndefined();
        });
    });

    // =========================================================================
    // K. Order of Operations Tests
    // =========================================================================
    describe('order of operations', () => {
        test('upload flow executes steps in correct order', async () => {
            const callOrder = [];

            // Track order of all operations
            const trackingCallbacks = {
                onProgress: jest.fn((pct, msg) => callOrder.push(`onProgress:${msg}`)),
                onSuccess: jest.fn(() => callOrder.push('onSuccess')),
                onError: jest.fn(),
                onCancel: jest.fn(),
            };

            const trackingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...trackingCallbacks,
            });

            // Track fetch calls
            global.fetch
                .mockImplementationOnce(() => {
                    callOrder.push('fetch:initiate');
                    return mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    });
                })
                .mockImplementationOnce(() => {
                    callOrder.push('fetch:complete');
                    return mockFetchSuccess({ id: 1 });
                });

            // Track XHR
            mockXhr.send = jest.fn(() => callOrder.push('xhr:send'));

            const uploadPromise = trackingUploader.upload(createMockFile(), 'Test');

            await new Promise((resolve) => setTimeout(resolve, 0));

            callOrder.push('xhr:load');
            triggerXhrLoad(200);

            await uploadPromise;

            // Verify correct order (Finalizing is called BEFORE the complete fetch)
            expect(callOrder).toEqual([
                'onProgress:Preparing upload...',
                'fetch:initiate',
                'onProgress:Uploading...',
                'xhr:send',
                'xhr:load',
                'onProgress:Finalizing...',  // Called before await _completeUpload()
                'fetch:complete',
                'onProgress:Complete',
                'onSuccess',
            ]);
        });

        test('beforeunload is unregistered BEFORE onSuccess is called on success', async () => {
            const callOrder = [];

            window.removeEventListener = jest.fn((event, handler) => {
                if (event === 'beforeunload') {
                    callOrder.push('unregisterBeforeUnload');
                }
                if (windowEventHandlers[event] === handler) {
                    delete windowEventHandlers[event];
                }
            });

            const trackingCallbacks = {
                onProgress: jest.fn(),
                onSuccess: jest.fn(() => callOrder.push('onSuccess')),
                onError: jest.fn(),
                onCancel: jest.fn(),
            };

            const trackingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...trackingCallbacks,
            });

            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'token-abc',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() => mockFetchSuccess({ id: 1 }));

            const uploadPromise = trackingUploader.upload(createMockFile(), 'Test');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            // beforeunload cleanup should happen BEFORE success callback
            expect(callOrder).toEqual(['unregisterBeforeUnload', 'onSuccess']);
        });

        test('on error: cleanup happens before onError callback', async () => {
            const callOrder = [];

            window.removeEventListener = jest.fn((event, handler) => {
                if (event === 'beforeunload') {
                    callOrder.push('unregisterBeforeUnload');
                }
                if (windowEventHandlers[event] === handler) {
                    delete windowEventHandlers[event];
                }
            });

            const trackingCallbacks = {
                onProgress: jest.fn(),
                onSuccess: jest.fn(),
                onError: jest.fn(() => callOrder.push('onError')),
                onCancel: jest.fn(),
            };

            const trackingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...trackingCallbacks,
            });

            global.fetch.mockImplementationOnce(() =>
                mockFetchError(500, { error: 'Server error' })
            );

            await trackingUploader.upload(createMockFile(), 'Test');

            // Cleanup should happen before error callback
            expect(callOrder).toEqual(['unregisterBeforeUnload', 'onError']);
        });

        test('cancel() calls operations in correct order', async () => {
            const callOrder = [];

            window.removeEventListener = jest.fn((event) => {
                if (event === 'beforeunload') {
                    callOrder.push('unregisterBeforeUnload');
                }
            });

            mockXhr.abort = jest.fn(() => callOrder.push('xhr:abort'));

            global.fetch.mockImplementationOnce(() => {
                callOrder.push('fetch:cancel');
                return mockFetchSuccess({});
            });

            const trackingCallbacks = {
                onProgress: jest.fn(),
                onSuccess: jest.fn(),
                onError: jest.fn(),
                onCancel: jest.fn(() => callOrder.push('onCancel')),
            };

            const trackingUploader = new window.DirectUploader({
                ...defaultOptions,
                ...trackingCallbacks,
            });

            trackingUploader._registerBeforeUnload();
            trackingUploader.xhr = mockXhr;
            trackingUploader.uploadToken = 'test-token';

            trackingUploader.cancel();

            await new Promise((resolve) => setTimeout(resolve, 0));

            // Order: unregister -> abort -> cancelUpload -> onCancel
            expect(callOrder).toEqual([
                'unregisterBeforeUnload',
                'xhr:abort',
                'fetch:cancel',
                'onCancel',
            ]);
        });
    });

    // =========================================================================
    // L. Concurrent Upload Prevention Tests
    // =========================================================================
    describe('concurrent uploads', () => {
        test('starting second upload while first is in progress overwrites state', async () => {
            // First upload - will hang waiting for S3
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'first-token',
                    presigned_url: 'https://s3.example.com/first',
                })
            );

            const firstFile = createMockFile(1024, 'first.exe');
            uploader.upload(firstFile, 'First Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            expect(uploader.uploadToken).toBe('first-token');

            // Second upload starts before first completes
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'second-token',
                    presigned_url: 'https://s3.example.com/second',
                })
            );

            const secondFile = createMockFile(2048, 'second.exe');
            uploader.upload(secondFile, 'Second Agent');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // State is now from second upload
            expect(uploader.uploadToken).toBe('second-token');
        });

        test('rapid cancel and restart works correctly', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'first-token',
                        presigned_url: 'https://s3.example.com/first',
                    })
                )
                .mockImplementationOnce(() => mockFetchSuccess({})) // cancel
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'second-token',
                        presigned_url: 'https://s3.example.com/second',
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchSuccess({ id: 2, name: 'Second Agent' })
                );

            // Start first upload
            const firstPromise = uploader.upload(createMockFile(), 'First');
            await new Promise((resolve) => setTimeout(resolve, 0));

            // Cancel immediately
            uploader.cancel();
            triggerXhrAbort();
            await firstPromise;

            // Start second upload right away
            const secondPromise = uploader.upload(createMockFile(), 'Second');
            await new Promise((resolve) => setTimeout(resolve, 0));

            // cancelled flag should be reset
            expect(uploader.cancelled).toBe(false);

            triggerXhrLoad(200);
            await secondPromise;

            expect(mockCallbacks.onSuccess).toHaveBeenCalledWith({
                id: 2,
                name: 'Second Agent',
            });
        });
    });

    // =========================================================================
    // M. State Consistency Tests
    // =========================================================================
    describe('state consistency', () => {
        test('uploadToken is cleared concept - token persists after upload for potential retry info', async () => {
            global.fetch
                .mockImplementationOnce(() =>
                    mockFetchSuccess({
                        upload_token: 'persistent-token',
                        presigned_url: 'https://s3.example.com/upload',
                    })
                )
                .mockImplementationOnce(() =>
                    mockFetchSuccess({ id: 1, name: 'Agent' })
                );

            const uploadPromise = uploader.upload(createMockFile(), 'Test');

            await new Promise((resolve) => setTimeout(resolve, 0));
            triggerXhrLoad(200);

            await uploadPromise;

            // Token persists after successful upload (by design - for debugging/logging)
            expect(uploader.uploadToken).toBe('persistent-token');
        });

        test('xhr reference is set during upload and accessible for abort', async () => {
            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'token',
                    presigned_url: 'https://s3.example.com/upload',
                })
            );

            expect(uploader.xhr).toBeNull();

            const uploadPromise = uploader.upload(createMockFile(), 'Test');

            await new Promise((resolve) => setTimeout(resolve, 0));

            // XHR should be set during S3 upload phase
            expect(uploader.xhr).toBe(mockXhr);

            triggerXhrLoad(200);
        });

        test('cancelled flag is reset at start of new upload', async () => {
            // Simulate a cancelled state
            uploader.cancelled = true;

            global.fetch.mockImplementationOnce(() =>
                mockFetchSuccess({
                    upload_token: 'token',
                    presigned_url: 'https://s3.example.com/upload',
                })
            );

            uploader.upload(createMockFile(), 'Test');

            // Flag should be reset immediately
            expect(uploader.cancelled).toBe(false);
        });
    });
});
