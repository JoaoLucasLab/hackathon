import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, unwrap } from "./client";
import { forgetPlanningSetup, rememberPlanningSetup } from "./planningSetup";
import type {
  AuditRequirement,
  BuildSchedulesResponse,
  ConstraintSet,
  DegreeAudit,
  FavoriteProfessor,
  Professor,
  Schedule,
  ScheduleExplanation,
} from "./schemas";

export const queryKeys = {
  audit: ["audit"] as const,
  /** The parsed audit waiting for the student to confirm it. Memory only. */
  auditDraft: ["audit", "draft"] as const,
  remaining: ["requirements", "remaining"] as const,
  professors: ["professors"] as const,
  explanation: (schedule: Schedule) =>
    [
      "schedule-explanation",
      schedule.id,
      schedule.classes.map((c) => c.section.id),
      schedule.why,
      schedule.warnings ?? [],
    ] as const,
};

/** Unmet requirements from the session's audit (`GET /api/requirements/remaining`). */
export function useRemainingRequirements() {
  return useQuery<AuditRequirement[]>({
    queryKey: queryKeys.remaining,
    queryFn: async () => unwrap(await api.GET("/api/requirements/remaining")),
  });
}

/** Records consent (`POST /api/session`), then loads the sample audit fixture. */
export function useStartWithSampleAudit() {
  const queryClient = useQueryClient();
  return useMutation<DegreeAudit>({
    mutationFn: async () => {
      unwrap(await api.POST("/api/session", { body: { consent: true } }));
      return unwrap(await api.POST("/api/audit/sample"));
    },
    onSuccess: (audit) => {
      rememberPlanningSetup();
      queryClient.setQueryData(queryKeys.audit, audit);
      void queryClient.invalidateQueries({ queryKey: queryKeys.remaining });
    },
  });
}

/** Deletes the audit, chats, favorites and session (`DELETE /api/me`). */
export function useDeleteMyData() {
  const queryClient = useQueryClient();
  return useMutation<void>({
    mutationFn: async () => {
      unwrap(await api.DELETE("/api/me"));
    },
    onSuccess: () => {
      forgetPlanningSetup();
      queryClient.clear();
    },
  });
}

/**
 * Saves the edited rules (`PUT /api/constraints`) and rebuilds the schedules
 * (`POST /api/schedules/build`). Used when a rule chip is removed; no Claude call.
 */
export function useRebuildSchedules() {
  return useMutation<BuildSchedulesResponse, Error, ConstraintSet>({
    mutationFn: async (constraints) => {
      unwrap(await api.PUT("/api/constraints", { body: constraints }));
      return unwrap(
        await api.POST("/api/schedules/build", { body: { constraints, max_results: 3 } }),
      );
    },
  });
}

/** All professors, each with `is_favorite` for this session (`GET /api/professors`). */
export function useProfessors() {
  return useQuery<Professor[]>({
    queryKey: queryKeys.professors,
    queryFn: async () => unwrap(await api.GET("/api/professors")),
    staleTime: 5 * 60_000,
  });
}

/**
 * Stars or unstars a professor (`PUT /api/professors/{id}/favorite`). The star
 * flips at once and flips back if the request fails. Stored per session on the
 * server, so it survives a reload.
 */
export function useToggleFavorite() {
  const queryClient = useQueryClient();
  return useMutation<
    FavoriteProfessor,
    Error,
    { professorId: string; favorite: boolean },
    { previous?: Professor[] }
  >({
    mutationFn: async ({ professorId, favorite }) =>
      unwrap(
        await api.PUT("/api/professors/{professor_id}/favorite", {
          params: { path: { professor_id: professorId } },
          body: { favorite },
        }),
      ),
    onMutate: async ({ professorId, favorite }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.professors });
      const previous = queryClient.getQueryData<Professor[]>(queryKeys.professors);
      queryClient.setQueryData<Professor[]>(queryKeys.professors, (list) =>
        list?.map((p) => (p.id === professorId ? { ...p, is_favorite: favorite } : p)),
      );
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(queryKeys.professors, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.professors }),
  });
}

/**
 * "Why this schedule" and the trade-offs, written by Claude from the solver's
 * structured `why` only (`POST /api/schedules/explain`).
 */
export function useScheduleExplanation(schedule: Schedule) {
  return useQuery<ScheduleExplanation>({
    queryKey: queryKeys.explanation(schedule),
    queryFn: async () =>
      unwrap(await api.POST("/api/schedules/explain", { body: { schedule } })),
    staleTime: Infinity,
  });
}

/**
 * Records consent, then sends the audit PDF to `POST /api/audit` to be read once.
 * The parsed audit is kept in memory as the draft for the confirm screen; nothing
 * is saved until the student confirms. Errors are `ApiError`s with the status:
 * 413 too large, 415 not a PDF, 422 could not be read.
 */
export function useUploadAudit() {
  const queryClient = useQueryClient();
  return useMutation<DegreeAudit, Error, File>({
    mutationFn: async (file) => {
      unwrap(await api.POST("/api/session", { body: { consent: true } }));
      const result = await api.POST("/api/audit", {
        body: { file: "" },
        bodySerializer: () => {
          const form = new FormData();
          form.append("file", file, file.name);
          return form;
        },
      });
      return unwrap(result);
    },
    onSuccess: (audit) => queryClient.setQueryData(queryKeys.auditDraft, audit),
  });
}

/** Saves the audit the student confirmed (`PUT /api/audit`). */
export function useConfirmAudit() {
  const queryClient = useQueryClient();
  return useMutation<DegreeAudit, Error, DegreeAudit>({
    mutationFn: async (audit) => unwrap(await api.PUT("/api/audit", { body: audit })),
    onSuccess: (audit) => {
      queryClient.setQueryData(queryKeys.audit, audit);
      queryClient.removeQueries({ queryKey: queryKeys.auditDraft, exact: true });
      void queryClient.invalidateQueries({ queryKey: queryKeys.remaining });
    },
  });
}

export function errorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}
