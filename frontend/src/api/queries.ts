import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { AuditRequirement, DegreeAudit } from "./schemas";

export const queryKeys = {
  audit: ["audit"] as const,
  remaining: ["requirements", "remaining"] as const,
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
    onSuccess: () => queryClient.clear(),
  });
}
