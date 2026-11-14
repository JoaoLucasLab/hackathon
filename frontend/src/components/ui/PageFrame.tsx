import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useDeleteMyData } from "../../api/queries";
import { Button } from "./Button";
import { Footnote } from "./Footnote";
import { NavBar } from "./NavBar";

interface PageFrameProps {
  title: string;
  lead?: string;
  footnote?: ReactNode;
  children: ReactNode;
}

/** The frame every screen uses: nav, one serif title, one lead line, content, footnote. */
export function PageFrame({ title, lead, footnote, children }: PageFrameProps) {
  const navigate = useNavigate();
  const deleteData = useDeleteMyData();

  return (
    <div className="flex min-h-screen flex-col">
      <NavBar />
      <main className="mx-auto flex w-full max-w-content flex-1 flex-col gap-6 px-5 pb-10 pt-14 md:px-6 md:pt-[72px]">
        <div className="flex flex-col gap-3">
          <h1 className="max-w-[17ch] font-serif text-[36px] font-normal leading-[1.05] tracking-[-0.015em] md:text-[52px]">
            {title}
          </h1>
          {lead && <p className="max-w-[60ch] text-[17px] leading-[1.5] text-muted">{lead}</p>}
        </div>
        {children}
      </main>
      <footer className="mx-auto flex w-full max-w-content flex-col gap-1 px-5 pb-8 md:px-6">
        {footnote && <Footnote>{footnote}</Footnote>}
        <div className="flex flex-wrap items-center gap-x-3">
          <Button
            variant="text"
            className="text-[13px]"
            disabled={deleteData.isPending}
            onClick={() =>
              deleteData.mutate(undefined, {
                onSuccess: () => navigate("/", { state: { deleted: true } }),
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
