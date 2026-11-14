import { Navigate, Route, Routes } from "react-router-dom";

import { Consent } from "./pages/Consent";
import { Planner } from "./pages/Planner";
import { Requirements } from "./pages/Requirements";

/** Opt in to React Router v7 behavior now, so the upgrade is a no-op. */
export const routerFuture = { v7_startTransition: true, v7_relativeSplatPath: true } as const;

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Consent />} />
      <Route path="/requirements" element={<Requirements />} />
      <Route path="/planner" element={<Planner />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
