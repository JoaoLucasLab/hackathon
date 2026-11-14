import type { ReactNode } from "react";

export function Footnote({ children }: { children: ReactNode }) {
  return <p className="text-[13px] text-muted">{children}</p>;
}
