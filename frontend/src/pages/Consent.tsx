import { useId, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useStartWithSampleAudit } from "../api/queries";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Icon, IconTile, type IconName } from "../components/ui/Icon";
import { PageFrame } from "../components/ui/PageFrame";
import { usePlanningState } from "./PlanningState";
import { FEATURES } from "../config";

const facts: { icon: IconName; text: string }[] = [
  {
    icon: "lock",
    text: "We store your degree audit's courses and requirements, your chat messages and your favorite professors, encrypted. We never store your name or student ID number.",
  },
  {
    icon: "send",
    text: "If you upload your audit, the PDF is sent to the Claude API once so it can be read.",
  },
  {
    icon: "fileX",
    text: "The PDF is deleted right after it is read. It is never saved.",
  },
  {
    icon: "trash",
    text: "Delete all your data at any time with “Delete my data” at the bottom of every page.",
  },
];

export function Consent() {
  const [agreed, setAgreed] = useState(false);
  const boxId = useId();
  const navigate = useNavigate();
  const location = useLocation();
  const start = useStartWithSampleAudit();
  const { setResults, clearChat } = usePlanningState();
  const justDeleted = (location.state as { deleted?: boolean } | null)?.deleted === true;

  const useSample = () =>
    start.mutate(undefined, { onSuccess: () => { clearChat(); setResults(null); navigate("/requirements"); } });

  return (
    <PageFrame
      title="Before you start"
      lead="Here is what the app keeps, and how to remove it."
      footnote="This app never asks for your BYU-Idaho username or password."
    >
      {justDeleted && (
        <p role="status" className="flex items-center gap-2 text-sm">
          <Icon name="check" size={16} />
          Your data was deleted.
        </p>
      )}

      <Card>
        <ul className="flex flex-col gap-4">
          {facts.map((fact) => (
            <li key={fact.icon} className="flex items-center gap-3">
              <IconTile name={fact.icon} size="sm" className="text-ink" />
              <span className="max-w-[64ch]">{fact.text}</span>
            </li>
          ))}
        </ul>
      </Card>

      <div className="flex items-center gap-3">
        <input
          id={boxId}
          type="checkbox"
          checked={agreed}
          onChange={(e) => setAgreed(e.target.checked)}
          className="size-5 shrink-0 cursor-pointer accent-ink"
        />
        <label htmlFor={boxId} className="cursor-pointer py-2">
          I understand what is stored and how to delete it
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {FEATURES.auditUpload && (
          // AI-04 adds the upload route behind FEATURE_AUDIT_UPLOAD.
          <Button variant="primary" disabled={!agreed} onClick={() => navigate("/audit")}>
            Upload my audit
          </Button>
        )}
        <Button
          variant={FEATURES.auditUpload ? "secondary" : "primary"}
          disabled={!agreed || start.isPending}
          aria-busy={start.isPending}
          onClick={useSample}
        >
          Use sample audit
        </Button>
      </div>

      {start.isError && (
        <p role="alert" className="flex items-start gap-2">
          <Icon name="alert" className="mt-0.5 shrink-0" />
          We couldn't start your session. Check your connection and try again.
        </p>
      )}
    </PageFrame>
  );
}
