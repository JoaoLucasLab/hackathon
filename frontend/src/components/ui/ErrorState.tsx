import type { ReactNode } from "react";

import { Button } from "./Button";
import { Card } from "./Card";
import { Icon } from "./Icon";

interface ErrorStateProps {
  /** One sentence: what happened and what to try. No red, no apologies. */
  message: string;
  onRetry: () => void;
  retrying?: boolean;
  /** An extra way forward, for example "Use sample audit". */
  extra?: ReactNode;
}

export function ErrorState({ message, onRetry, retrying = false, extra }: ErrorStateProps) {
  return (
    <Card className="flex flex-col items-start gap-4">
      <p role="alert" className="flex items-start gap-2">
        <Icon name="alert" className="mt-0.5 shrink-0" />
        <span>{message}</span>
      </p>
      <div className="flex flex-wrap gap-3">
        <Button variant="primary" onClick={onRetry} disabled={retrying} aria-busy={retrying}>
          Try again
        </Button>
        {extra}
      </div>
    </Card>
  );
}
