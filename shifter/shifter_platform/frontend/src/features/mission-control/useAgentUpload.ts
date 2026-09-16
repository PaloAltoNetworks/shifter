/**
 * Agent-upload state machine (#1370): initiate -> presigned S3 PUT (with
 * progress) -> complete. Client-side counterpart to the legacy
 * `DirectUploader` (`static/js/upload.js`), matching its three-step flow and
 * field names.
 *
 * The per-file size guard uses the server-owned ceiling delivered on the
 * agent-list response (`max_file_size_bytes`, #94), not a client constant, so
 * the frontend limit cannot drift from what the backend enforces. When the cap
 * has not loaded yet the guard fails closed rather than assuming a default.
 *
 * No step ever auto-retries (ADR-029 / `api/queryClient.ts`): a failure at
 * any step surfaces `error` and returns to `idle`, requiring an explicit new
 * `start()` call from the user.
 */
import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { ApiError } from "@/api/errors";
import {
  useCancelUpload,
  useCompleteUpload,
  useInitiateUpload,
  type UploadInitiateRequest,
} from "@/api/mission-control";

import { uploadFileToPresignedUrl, type PresignedUploadHandle } from "./upload";

export type AgentType = NonNullable<UploadInitiateRequest["agent_type"]>;

export type AgentUploadPhase = "idle" | "uploading" | "error";

export interface UseAgentUploadOptions {
  /**
   * Server-owned per-file ceiling in bytes (`max_file_size_bytes` from the
   * agent-list response). `undefined` while that response is still loading or
   * failed; the pre-initiation guard fails closed in that case.
   */
  maxSizeBytes: number | undefined;
}

export interface AgentUploadState {
  phase: AgentUploadPhase;
  progress: number;
  statusText: string;
  error: string | null;
}

export interface StartUploadArgs {
  name: string;
  file: File;
  agentType: AgentType;
}

export interface UseAgentUploadResult extends AgentUploadState {
  start: (args: StartUploadArgs) => void;
  /** Abort the in-flight PUT (if any) and best-effort clean up the upload session server-side. */
  cancel: () => void;
}

const INITIAL_STATE: AgentUploadState = { phase: "idle", progress: 0, statusText: "", error: null };

/** Render a failed upload step's error into user-facing copy. */
function describeUploadError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Upload failed.";
}

function reportUploadProgress(setState: Dispatch<SetStateAction<AgentUploadState>>, percent: number) {
  setState((prev) => ({ ...prev, progress: percent, statusText: `Uploading… ${percent}%` }));
}

interface RunUploadSequenceArgs {
  name: string;
  file: File;
  agentType: AgentType;
  cancelledRef: MutableRefObject<boolean>;
  uploadTokenRef: MutableRefObject<string | null>;
  putHandleRef: MutableRefObject<PresignedUploadHandle | null>;
  setState: Dispatch<SetStateAction<AgentUploadState>>;
  initiateUpload: ReturnType<typeof useInitiateUpload>;
  completeUpload: ReturnType<typeof useCompleteUpload>;
  cancelUpload: ReturnType<typeof useCancelUpload>;
}

/**
 * Run the initiate -> presigned PUT -> complete sequence for one `start()`
 * call. Declared at module scope (rather than as a closure inside `start`)
 * so the presigned-PUT progress callback below is only one function deep,
 * not nested inside an outer callback *and* an async IIFE.
 */
async function runUploadSequence({
  name,
  file,
  agentType,
  cancelledRef,
  uploadTokenRef,
  putHandleRef,
  setState,
  initiateUpload,
  completeUpload,
  cancelUpload,
}: RunUploadSequenceArgs): Promise<void> {
  try {
    const initiated = await initiateUpload.mutateAsync({
      name,
      filename: file.name,
      file_size: file.size,
      agent_type: agentType,
    });
    if (cancelledRef.current) return;
    uploadTokenRef.current = initiated.upload_token;

    setState((prev) => ({ ...prev, statusText: "Uploading…" }));
    const handle = uploadFileToPresignedUrl(initiated.presigned_url, file, (percent) =>
      reportUploadProgress(setState, percent),
    );
    putHandleRef.current = handle;
    await handle.promise;
    if (cancelledRef.current) return;

    setState((prev) => ({ ...prev, statusText: "Finalizing…" }));
    await completeUpload.mutateAsync({ upload_token: initiated.upload_token });
    if (cancelledRef.current) return;

    setState(INITIAL_STATE);
  } catch (err) {
    if (cancelledRef.current) return;
    setState({ phase: "error", progress: 0, statusText: "", error: describeUploadError(err) });
    // Best-effort server-side cleanup of the upload-in-progress session
    // marker; a cleanup failure never overrides the error already shown.
    if (uploadTokenRef.current) {
      cancelUpload.mutate({ upload_token: uploadTokenRef.current });
    }
  }
}

export function useAgentUpload({ maxSizeBytes }: UseAgentUploadOptions): UseAgentUploadResult {
  const initiateUpload = useInitiateUpload();
  const completeUpload = useCompleteUpload();
  const cancelUpload = useCancelUpload();

  const [state, setState] = useState<AgentUploadState>(INITIAL_STATE);
  const inFlightRef = useRef(false);
  const cancelledRef = useRef(false);
  const uploadTokenRef = useRef<string | null>(null);
  const putHandleRef = useRef<PresignedUploadHandle | null>(null);

  const start = useCallback(
    ({ name, file, agentType }: StartUploadArgs) => {
      if (inFlightRef.current) return;

      const trimmedName = name.trim();
      if (!trimmedName) {
        setState({ phase: "error", progress: 0, statusText: "", error: "Agent name is required." });
        return;
      }
      if (maxSizeBytes === undefined) {
        setState({
          phase: "error",
          progress: 0,
          statusText: "",
          error: "Upload limit is unavailable right now. Please retry in a moment.",
        });
        return;
      }
      if (file.size > maxSizeBytes) {
        const maxMb = Math.floor(maxSizeBytes / 1024 / 1024);
        setState({
          phase: "error",
          progress: 0,
          statusText: "",
          error: `File size exceeds the maximum (${maxMb} MB).`,
        });
        return;
      }

      inFlightRef.current = true;
      cancelledRef.current = false;
      uploadTokenRef.current = null;
      putHandleRef.current = null;
      setState({ phase: "uploading", progress: 0, statusText: "Preparing upload…", error: null });

      void runUploadSequence({
        name: trimmedName,
        file,
        agentType,
        cancelledRef,
        uploadTokenRef,
        putHandleRef,
        setState,
        initiateUpload,
        completeUpload,
        cancelUpload,
      }).finally(() => {
        inFlightRef.current = false;
        putHandleRef.current = null;
      });
    },
    [initiateUpload, completeUpload, cancelUpload, maxSizeBytes],
  );

  const cancel = useCallback(() => {
    if (!inFlightRef.current) return;
    cancelledRef.current = true;
    putHandleRef.current?.abort();
    if (uploadTokenRef.current) {
      cancelUpload.mutate({ upload_token: uploadTokenRef.current });
    }
    inFlightRef.current = false;
    setState(INITIAL_STATE);
  }, [cancelUpload]);

  return { ...state, start, cancel };
}
