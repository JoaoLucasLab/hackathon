import { Navigate, Route, Routes } from "react-router-dom";

import { AuditConfirm } from "./pages/AuditConfirm";
import { AuditUpload } from "./pages/AuditUpload";
import { conversationalPlanner } from "./config";
import { Consent } from "./pages/Consent";
import { MyPlan } from "./pages/MyPlan";
import { Planner } from "./pages/Planner";
import { MentorFinder } from "./pages/MentorFinder";
import { Professor } from "./pages/Professor";
import { PlanningState } from "./pages/PlanningState";
import { Requirements } from "./pages/Requirements";

/** Opt in to React Router v7 behavior now, so the upgrade is a no-op. */
export const routerFuture = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

export function AppRoutes() {
  // AI-08: with the conversational planner, the Schedules tab is "My plan".
  const myPlan = conversationalPlanner();
  return (
    <PlanningState>
      <Routes>
        <Route element={<Planner />}>
          <Route path="/" element={null} />
          <Route path="/planner" element={null} />
          {!myPlan && <Route path="/schedules" element={null} />}
        </Route>
      {myPlan && <Route path="/plan" element={<MyPlan />} />}
      {myPlan && <Route path="/schedules" element={<Navigate to="/plan" replace />} />}
      <Route path="/consent" element={<Consent />} />
      <Route path="/professors" element={<MentorFinder />} />
      <Route path="/professors/:professorId" element={<Professor />} />
      <Route path="/audit" element={<AuditUpload />} />
      <Route path="/audit/confirm" element={<AuditConfirm />} />
      <Route path="/requirements" element={<Requirements />} />
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </PlanningState>
  );
}
