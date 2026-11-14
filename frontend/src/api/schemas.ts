// Aliases for the generated contract types. Nothing here is written by hand:
// every type points into `types.ts`, which `npm run gen:types` generates.
import type { components } from "./types";

type Schemas = components["schemas"];

export type AuditRequirement = Schemas["AuditRequirement"];
export type DegreeAudit = Schemas["DegreeAudit"];
export type AuditCourse = Schemas["AuditCourse"];
export type ValidationFlag = Schemas["ValidationFlag"];
export type Track = Schemas["Track"];
export type SessionResponse = Schemas["SessionResponse"];
export type BuildSchedulesResponse = Schemas["BuildSchedulesResponse"];
export type ChatEvent = Schemas["ChatEvent"];
export type ChatHistory = Schemas["ChatHistory"];
export type SavedChatTurn = Schemas["ChatTurn"];
export type ConstraintSet = Schemas["ConstraintSet"];
export type Day = Schemas["Day"];
export type Meeting = Schemas["Meeting"];
export type Schedule = Schemas["Schedule"];
export type ScheduledClass = Schemas["ScheduledClass"];
export type Section = Schemas["Section"];
export type Professor = Schemas["Professor"];
export type FavoriteProfessor = Schemas["FavoriteProfessor"];
export type ScheduleExplanation = Schemas["ScheduleExplanation"];
export type Relaxation = Schemas["Relaxation"];
export type MentorGoal = Schemas["MentorGoal"];
export type MentorMatch = Schemas["MentorMatch"];
export type EmailDraft = Schemas["EmailDraft"];
export type ProfessorSource = Schemas["ProfessorSource"];
