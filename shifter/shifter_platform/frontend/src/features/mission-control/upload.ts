/**
 * Presigned S3 PUT for the agent-upload flow (#1370).
 *
 * This is the one deliberate exception to "every request goes through
 * `apiFetch`": `presigned_url` (from `POST /mission-control/upload/initiate/`)
 * points at storage, not `/api/v1`, so it is sent with `Content-Type:
 * application/octet-stream` and no CSRF header or credentials, matching the
 * legacy `static/js/upload.js` `DirectUploader._uploadToS3` request exactly.
 * `XMLHttpRequest` (not `fetch`) is used deliberately: it is the only browser
 * API that reports upload progress, which the legacy uploader (and this page)
 * surfaces as a progress bar.
 *
 * The signed URL itself is never logged — only the resulting HTTP status or
 * error message reaches component state.
 */

export interface PresignedUploadHandle {
  /** Resolves once the PUT completes successfully, rejects otherwise. */
  promise: Promise<void>;
  /** Abort the in-flight PUT (surfaces as an "Upload cancelled" rejection). */
  abort: () => void;
}

/** PUT `file` to a presigned storage URL, reporting 0-100 progress along the way. */
export function uploadFileToPresignedUrl(
  url: string,
  file: File,
  onProgress: (percent: number) => void,
): PresignedUploadHandle {
  const xhr = new XMLHttpRequest();

  const promise = new Promise<void>((resolve, reject) => {
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}`));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Network error during upload")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelled")));

    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.send(file);
  });

  return { promise, abort: () => xhr.abort() };
}
