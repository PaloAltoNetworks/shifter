import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { uploadFileToPresignedUrl } from "./upload";

type ProgressListener = (event: { lengthComputable: boolean; loaded: number; total: number }) => void;
type SimpleListener = () => void;

/** Minimal `XMLHttpRequest` test double driven from the "server" side via `emit*`. */
class FakeXHR {
  static instances: FakeXHR[] = [];

  status = 0;
  readonly requestHeaders: Record<string, string> = {};
  method = "";
  url = "";
  sentBody: unknown;
  aborted = false;

  upload = { addEventListener: (_type: "progress", listener: ProgressListener) => (this.onProgress = listener) };
  private onProgress: ProgressListener | null = null;
  private onLoad: SimpleListener | null = null;
  private onError: SimpleListener | null = null;
  private onAbort: SimpleListener | null = null;

  constructor() {
    FakeXHR.instances.push(this);
  }

  addEventListener(type: "load" | "error" | "abort", listener: SimpleListener): void {
    if (type === "load") this.onLoad = listener;
    if (type === "error") this.onError = listener;
    if (type === "abort") this.onAbort = listener;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.requestHeaders[name] = value;
  }

  send(body: unknown): void {
    this.sentBody = body;
  }

  abort(): void {
    this.aborted = true;
    this.onAbort?.();
  }

  emitProgress(loaded: number, total: number): void {
    this.onProgress?.({ lengthComputable: true, loaded, total });
  }

  emitLoad(status: number): void {
    this.status = status;
    this.onLoad?.();
  }

  emitError(): void {
    this.onError?.();
  }
}

function latestXhr(): FakeXHR {
  const xhr = FakeXHR.instances.at(-1);
  if (!xhr) throw new Error("No FakeXHR instance was created");
  return xhr;
}

beforeEach(() => {
  FakeXHR.instances = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadFileToPresignedUrl", () => {
  it("PUTs the file with the legacy octet-stream header and no auth headers", () => {
    const file = new File(["contents"], "agent.zip");
    uploadFileToPresignedUrl("https://s3.example.test/bucket/key?sig=abc", file, () => {});

    const xhr = latestXhr();
    expect(xhr.method).toBe("PUT");
    expect(xhr.url).toBe("https://s3.example.test/bucket/key?sig=abc");
    expect(xhr.requestHeaders).toEqual({ "Content-Type": "application/octet-stream" });
    expect(xhr.sentBody).toBe(file);
  });

  it("reports rounded percent progress as the upload advances", () => {
    const progress: number[] = [];
    const file = new File(["x".repeat(100)], "agent.zip");
    uploadFileToPresignedUrl("https://s3.example.test/put", file, (percent) => progress.push(percent));

    const xhr = latestXhr();
    xhr.emitProgress(25, 100);
    xhr.emitProgress(100, 100);

    expect(progress).toEqual([25, 100]);
  });

  it("resolves once the PUT completes with a 2xx status", async () => {
    const file = new File(["x"], "agent.zip");
    const { promise } = uploadFileToPresignedUrl("https://s3.example.test/put", file, () => {});

    latestXhr().emitLoad(200);

    await expect(promise).resolves.toBeUndefined();
  });

  it("rejects with the status code when the PUT fails", async () => {
    const file = new File(["x"], "agent.zip");
    const { promise } = uploadFileToPresignedUrl("https://s3.example.test/put", file, () => {});

    latestXhr().emitLoad(500);

    await expect(promise).rejects.toThrow("Upload failed with status 500");
  });

  it("rejects on a network error", async () => {
    const file = new File(["x"], "agent.zip");
    const { promise } = uploadFileToPresignedUrl("https://s3.example.test/put", file, () => {});

    latestXhr().emitError();

    await expect(promise).rejects.toThrow("Network error during upload");
  });

  it("rejects with a cancellation message when aborted", async () => {
    const file = new File(["x"], "agent.zip");
    const { promise, abort } = uploadFileToPresignedUrl("https://s3.example.test/put", file, () => {});

    abort();

    await expect(promise).rejects.toThrow("Upload cancelled");
    expect(latestXhr().aborted).toBe(true);
  });
});
