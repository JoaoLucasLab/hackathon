// Aliases for the generated contract types. Nothing here is written by hand:
// every type points into `types.ts`, which `npm run gen:types` generates.
import type { components } from "./types";

type Schemas = components["schemas"];

export type AuditRequirement = Schemas["AuditRequirement"];
export type DegreeAudit = Schemas["DegreeAudit"];
export type SessionResponse = Schemas["SessionResponse"];
export type BuildSchedulesResponse = Schemas["BuildSchedulesResponse"];
export type ChatEvent = Schemas["ChatEvent"];
export type ConstraintSet = Schemas["ConstraintSet"];
export type Day = Schemas["Day"];
export type Meeting = Schemas["Meeting"];
export type Schedule = Schemas["Schedule"];
export type ScheduledClass = Schemas["ScheduledClass"];
export type Section = Schemas["Section"];
