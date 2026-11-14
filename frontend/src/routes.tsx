import { Navigate, Route, Routes } from "react-router-dom";

import { AuditConfirm } from "./pages/AuditConfirm";
import { AuditUpload } from "./pages/AuditUpload";
import { Consent } from "./pages/Consent";
import { Planner } from "./pages/Planner";
import { MentorFinder } from "./pages/MentorFinder";
import { PlanningState } from "./pages/PlanningState";
import { Requirements } from "./pages/Requirements";

/** Opt in to React Router v7 behavior now, so the upgrade is a no-op. */
export const routerFuture = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

export function AppRoutes() {
  return (
    <PlanningState>
      <Routes>
        <Route element={<Planner />}>
          <Route path="/" element={null} />
          <Route path="/planner" element={null} />
          <Route path="/schedules" element={null} />
        </Route>
      <Route path="/consent" element={<Consent />} />
      <Route path="/professors" element={<MentorFinder />} />
      <Route path="/audit" element={<AuditUpload />} />
      <Route path="/audit/confirm" element={<AuditConfirm />} />
      <Route path="/requirements" element={<Requirements />} />
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </PlanningState>
  );
}
