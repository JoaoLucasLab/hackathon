import { Button } from "./Button";
import { Card } from "./Card";

interface EmptyProps {
  /** One sentence that says what to do. */
  message: string;
  actionLabel: string;
  onAction: () => void;
}

export function Empty({ message, actionLabel, onAction }: EmptyProps) {
  return (
    <Card className="flex flex-col items-start gap-4">
      <p>{message}</p>
      <Button variant="primary" onClick={onAction}>
        {actionLabel}
      </Button>
    </Card>
  );
}
