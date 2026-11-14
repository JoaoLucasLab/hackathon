import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { usePlanningState } from "../../pages/PlanningState";
import { useDeleteMyData } from "../../api/queries";
import { Button } from "./Button";
import { Footnote } from "./Footnote";
import { NavBar } from "./NavBar";

interface PageFrameProps {
  title?: string;
  home?: boolean;
  wide?: boolean;
  lead?: string;
  footnote?: ReactNode;
  children: ReactNode;
}

/** The frame every screen uses: nav, one serif title, one lead line, content, footnote. */
export function PageFrame({ title, lead, footnote, children, home = false, wide = false }: PageFrameProps) {
  const navigate = useNavigate();
  const deleteData = useDeleteMyData();
  const { setResults, setDraft, clearChat } = usePlanningState();

  return (
    <div className={`flex min-h-screen flex-col ${home && !wide ? "plan-entry" : ""}`}>
      <NavBar />
      <main className={`relative mx-auto flex w-full flex-1 flex-col gap-8 px-5 pb-10 md:px-6 ${wide ? "max-w-grid" : "max-w-content"} ${home && !wide ? "pt-20 md:pt-24" : "pt-14 md:pt-16"}`}>
        {title && <div className={`flex flex-col gap-6 ${home ? "items-center text-center" : ""}`}>
          <h1 className={`page-title ${wide ? "max-w-full" : "max-w-[17ch]"} font-serif font-normal leading-[1.04] tracking-[-0.025em] ${home && !wide ? "text-[42px] md:text-[68px]" : "text-[36px] md:text-[56px]"}`}>
            {title}
          </h1>
          {lead && <p className="page-lead max-w-[60ch] text-[17px] leading-[1.5] text-muted">{lead}</p>}
        </div>}
        {children}
      </main>
      <footer className={`mx-auto flex w-full max-w-content flex-col gap-1 px-5 pb-8 md:px-6 ${home ? "items-center text-center" : ""}`}>
        {footnote && <Footnote>{footnote}</Footnote>}
        <div className="flex flex-wrap items-center gap-x-3">
          <Button
            variant="text"
            className="text-[13px]"
            disabled={deleteData.isPending}
            onClick={() =>
              deleteData.mutate(undefined, {
                onSuccess: () => { clearChat(); setResults(null); setDraft(""); navigate("/consent", { state: { deleted: true } }); },
              })
            }
          >
            Delete my data
          </Button>
          {deleteData.isError && (
            <span role="alert" className="text-[13px]">
              We couldn't delete your data. Check your connection and try again.
            </span>
          )}
        </div>
      </footer>
    </div>
  );
}
