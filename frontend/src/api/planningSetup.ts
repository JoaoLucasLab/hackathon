/** A navigation hint only. The API remains responsible for session authorization.
 * Never store audit fields, chat text, identifiers or credentials here.
 */
const SETUP_KEY = "planning-setup-complete";

export function hasPlanningSetup(): boolean {
  try {
    return localStorage.getItem(SETUP_KEY) === "true";
  } catch {
    return false;
  }
}

export function rememberPlanningSetup(): void {
  try {
    localStorage.setItem(SETUP_KEY, "true");
  } catch {
    // Planning still works for this visit when browser storage is unavailable.
  }
}

export function forgetPlanningSetup(): void {
  try {
    localStorage.removeItem(SETUP_KEY);
  } catch {
    // Server-side deletion and in-memory cleanup must still complete.
  }
}
