// Aliases for the generated contract types. Nothing here is written by hand:
// every type points into `types.ts`, which `npm run gen:types` generates.
import type { components } from "./types";

type Schemas = components["schemas"];

export type AuditRequirement = Schemas["AuditRequirement"];
export type DegreeAudit = Schemas["DegreeAudit"];
export type SessionResponse = Schemas["SessionResponse"];
