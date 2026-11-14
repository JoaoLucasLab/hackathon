/** Placeholder until the team picks a name. Never put "BYU" or "BYU-Idaho" in it. */
export const APP_NAME = "Course planner";

export const TERM_LABEL = "Winter 2027";

export const FEATURES = {
  /** "Upload my audit" on the consent screen. Off until AI-04 merges. */
  auditUpload: import.meta.env.VITE_FEATURE_AUDIT_UPLOAD === "true",
} as const;
