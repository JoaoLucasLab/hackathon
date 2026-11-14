import { useId, useState, type ChangeEvent, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";

import { errorStatus, useStartWithSampleAudit, useUploadAudit } from "../api/queries";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/ErrorState";
import { Icon } from "../components/ui/Icon";
import { PageFrame } from "../components/ui/PageFrame";

/** Same limit as the backend (`AUDIT_MAX_BYTES`); the server checks it again. */
export const MAX_BYTES = 10 * 1024 * 1024;

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function fileProblem(file: File): string | null {
  if (!isPdf(file)) return "This file is not a PDF. Download your degree audit as a PDF.";
  if (file.size > MAX_BYTES) return "This file is larger than 10 MB. Upload the audit PDF only.";
  return null;
}

function uploadErrorMessage(error: unknown): string {
  switch (errorStatus(error)) {
    case 413:
      return "This file is larger than 10 MB. Upload the degree audit PDF only.";
    case 415:
      return "This file is not a PDF. Download your degree audit as a PDF and upload that.";
    case 404:
      return "Audit upload is turned off right now. Use the sample audit instead.";
    case null:
      return "We couldn't reach the server. Check your connection and try again.";
    default:
      return "We couldn't read this audit.";
  }
}

export function AuditUpload() {
  const inputId = useId();
  const hintId = useId();
  const navigate = useNavigate();
  const upload = useUploadAudit();
  const sample = useStartWithSampleAudit();
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const choose = (chosen: File | undefined) => {
    upload.reset();
    if (!chosen) return;
    const issue = fileProblem(chosen);
    setProblem(issue);
    setFile(issue ? null : chosen);
  };

  const send = () => {
    if (file) upload.mutate(file, { onSuccess: () => navigate("/audit/confirm") });
  };

  const useSample = () =>
    sample.mutate(undefined, { onSuccess: () => navigate("/requirements") });

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files[0]);
  };

  let body;
  if (upload.isPending) {
    body = (
      <Card role="status" aria-live="polite" className="flex flex-col gap-3">
        <p className="font-semibold">Reading your audit</p>
        <p className="text-muted">This can take up to a minute. Keep this page open.</p>
        <div aria-hidden="true" className="flex flex-col gap-2">
          <div className="h-4 w-2/3 rounded bg-field motion-safe:animate-pulse" />
          <div className="h-4 w-1/2 rounded bg-field motion-safe:animate-pulse" />
          <div className="h-4 w-3/5 rounded bg-field motion-safe:animate-pulse" />
        </div>
      </Card>
    );
  } else if (upload.isError) {
    body = (
      <ErrorState
        message={uploadErrorMessage(upload.error)}
        onRetry={() => {
          if (errorStatus(upload.error) === 413 || errorStatus(upload.error) === 415) {
            upload.reset();
            setFile(null);
          } else {
            send();
          }
        }}
        extra={
          <Button disabled={sample.isPending} aria-busy={sample.isPending} onClick={useSample}>
            Use sample audit
          </Button>
        }
      />
    );
  } else {
    body = (
      <>
        <label
          htmlFor={inputId}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-card border-2 border-dashed bg-surface px-6 py-10 text-center transition-colors ${
            dragging ? "border-ink" : "border-line"
          } focus-within:border-ink`}
        >
          <Icon name="upload" size={24} />
          <span className="font-semibold">
            {file ? file.name : "Choose your degree audit PDF"}
          </span>
          <span id={hintId} className="text-sm text-muted">
            {file ? "Choose a different file" : "Or drop it here. PDF, up to 10 MB."}
          </span>
          <input
            id={inputId}
            type="file"
            accept="application/pdf,.pdf"
            aria-describedby={hintId}
            className="sr-only"
            onChange={(e: ChangeEvent<HTMLInputElement>) => choose(e.target.files?.[0])}
          />
        </label>
        {problem && (
          <p role="alert" className="flex items-start gap-2">
            <Icon name="alert" className="mt-0.5 shrink-0" />
            {problem}
          </p>
        )}
        <Button variant="primary" className="self-start" disabled={!file} onClick={send}>
          Read my audit
        </Button>
      </>
    );
  }

  return (
    <PageFrame
      title="Upload your degree audit"
      lead="We read it once to find what you still need. The PDF is never saved."
      footnote="Your name and student ID number are never stored."
    >
      {body}
      {sample.isError && (
        <p role="alert" className="flex items-start gap-2">
          <Icon name="alert" className="mt-0.5 shrink-0" />
          We couldn't load the sample audit. Check your connection and try again.
        </p>
      )}
    </PageFrame>
  );
}
