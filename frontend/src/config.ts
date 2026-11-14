/** Placeholder until the team picks a name. Never put "BYU" or "BYU-Idaho" in it. */
export const APP_NAME = "Course planner";

export const TERM_LABEL = "Winter 2027";

export const FEATURES = {
  /** "Upload my audit" on the consent screen. Off until AI-04 merges. */
  auditUpload: import.meta.env.VITE_FEATURE_AUDIT_UPLOAD === "true",
} as const;

/**
 * AI-07 / AI-08: the chat asks first, shows one schedule at a time inside the
 * conversation, and the Schedules tab becomes "My plan". Must match the backend's
 * FEATURE_CONVERSATIONAL_PLANNER. A function, so tests can switch it with vi.stubEnv.
 */
export function conversationalPlanner(): boolean {
  return import.meta.env.VITE_FEATURE_CONVERSATIONAL_PLANNER === "true";
}
