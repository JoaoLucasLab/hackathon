import { RotateCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useStartOver } from "../api/queries";
import { usePlanningState } from "../pages/PlanningState";
import { Button } from "./ui/Button";
import { ICON_STROKE } from "./ui/Icon";

export const START_NEW = "Start a new plan";

/**
 * Clears the conversation and the confirmed plan (here and on the server) and
 * opens an empty chat. The audit and favorite professors stay.
 */
export function StartNewPlan({ variant = "secondary" }: { variant?: "secondary" | "text" }) {
  const navigate = useNavigate();
  const clear = useStartOver();
  const { clearChat, setResults, setDraft } = usePlanningState();

  return (
    <div className={`flex flex-col gap-1 ${variant === "text" ? "items-center text-center" : "items-start"}`}>
      <Button
        variant={variant}
        disabled={clear.isPending}
        onClick={() =>
          clear.mutate(undefined, {
            onSuccess: () => {
              clearChat();
              setResults(null);
              setDraft("");
              navigate("/");
            },
          })
        }
      >
        <RotateCcw size={16} strokeWidth={ICON_STROKE} aria-hidden="true" />
        {clear.isPending ? "Starting over" : START_NEW}
      </Button>
      {clear.isError && (
        <p role="alert" className="text-[13px]">
          We couldn't start a new plan. Check your connection and try again.
        </p>
      )}
    </div>
  );
}
