/**
 * Form-state model and (de)serialization helpers for the CTF organizer challenge
 * create/edit form. Split out of ChallengeFormPage so the page component and its
 * section components can share the shape without a circular import.
 */
import type { CtfChallengeWrite, CtfOrganizerChallengeDetail } from "@/api/types";

import { fromDateTimeLocalValue, toDateTimeLocalValue } from "../format";

export interface FormState {
  name: string;
  description: string;
  category: string;
  difficulty: string;
  points: string;
  order: string;
  max_attempts: string;
  minimum_points: string;
  decay_function: string;
  decay_solve_count: string;
  flag_format: string;
  solution: string;
  visibility: string;
  release_time: string;
  target_instance_name: string;
  target_port: string;
  tags: string;
  topics: string;
  flag: string;
}

export const EMPTY: FormState = {
  name: "",
  description: "",
  category: "web",
  difficulty: "easy",
  points: "100",
  order: "0",
  max_attempts: "0",
  minimum_points: "0",
  decay_function: "linear",
  decay_solve_count: "0",
  flag_format: "",
  solution: "",
  visibility: "visible",
  release_time: "",
  target_instance_name: "",
  target_port: "",
  tags: "",
  topics: "",
  flag: "",
};

export function fromChallenge(challenge: CtfOrganizerChallengeDetail): FormState {
  return {
    name: challenge.name ?? "",
    description: challenge.description ?? "",
    category: challenge.category || "web",
    difficulty: challenge.difficulty || "easy",
    points: String(challenge.points ?? 0),
    order: String(challenge.order ?? 0),
    max_attempts: String(challenge.max_attempts ?? 0),
    minimum_points: String(challenge.minimum_points ?? 0),
    decay_function: challenge.decay_function || "linear",
    decay_solve_count: String(challenge.decay_solve_count ?? 0),
    flag_format: challenge.flag_format ?? "",
    solution: challenge.solution ?? "",
    visibility: challenge.visibility || "visible",
    release_time: toDateTimeLocalValue(challenge.release_time),
    target_instance_name: challenge.target_instance_name ?? "",
    target_port: challenge.target_port == null ? "" : String(challenge.target_port),
    tags: (challenge.tags ?? []).join(", "),
    topics: (challenge.topics ?? []).join(", "),
    flag: "",
  };
}

export function intOr(value: string, fallback: number): number {
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : fallback;
}

function csvToList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function toPayload(state: FormState, mode: "create" | "edit"): CtfChallengeWrite {
  const port = state.target_port.trim();
  const base: CtfChallengeWrite = {
    name: state.name,
    description: state.description,
    category: state.category,
    difficulty: state.difficulty,
    points: intOr(state.points, 0),
    order: intOr(state.order, 0),
    max_attempts: intOr(state.max_attempts, 0),
    minimum_points: intOr(state.minimum_points, 0),
    decay_function: state.decay_function,
    decay_solve_count: intOr(state.decay_solve_count, 0),
    flag_format: state.flag_format,
    solution: state.solution,
    visibility: state.visibility,
    release_time: fromDateTimeLocalValue(state.release_time),
    target_instance_name: state.target_instance_name,
    target_port: port === "" ? null : intOr(port, 0),
    tags: csvToList(state.tags),
    topics: csvToList(state.topics),
  };
  // The flag is set on create; in edit mode flags are managed in their own
  // section (the SPA never resends the plaintext flag on an update).
  return mode === "create" && state.flag.trim() ? { ...base, flag: state.flag.trim() } : base;
}
