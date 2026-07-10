/**
 * Typed wrapper over the shared DRF error envelope
 * (`shared.api.errors`): `{ error: { code, message, details?, request_id? } }`.
 */

export interface ApiErrorEnvelope {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, envelope: ApiErrorEnvelope) {
    super(envelope.message || `API error (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = envelope.code;
    this.details = envelope.details;
    this.requestId = envelope.request_id;
  }

  /** Normalize `details` into a field -> messages map for form display. */
  fieldErrors(): Record<string, string[]> {
    const out: Record<string, string[]> = {};
    if (!this.details) return out;
    for (const [field, raw] of Object.entries(this.details)) {
      if (Array.isArray(raw)) {
        out[field] = raw.map(String);
      } else if (typeof raw === "string") {
        out[field] = [raw];
      } else if (raw != null) {
        out[field] = [JSON.stringify(raw)];
      }
    }
    return out;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
