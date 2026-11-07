/** Upload Report: pick or drop a PDF or text file, give it an optional title, and land on the new Report. Extraction
 * runs inside the upload request, so the dialog holds the Analyst in an "Extracting Insights" state until it returns and
 * cannot be dismissed by accident meanwhile. The server stays the only enforcement point; the browser only rejects what
 * it can already tell the server would refuse. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type DragEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api } from "./api/client";
import { reportPath, type Report, type ReportList } from "./research";
import { ErrorLine, Icon, trapTab } from "./ui";

/** The server's limit (MAX_UPLOAD_BYTES in app/routers/reports.py). */
const MAX_BYTES = 20 * 1024 * 1024;
/** The extensions the server reads (extract_pages in app/reports.py), which decides by file name, not media type. */
const EXTENSIONS = [".pdf", ".txt", ".md"];
const ACCEPT = [...EXTENSIONS, "application/pdf", "text/plain", "text/markdown"].join(",");

const MB = 1024 * 1024;
const LIMIT = `${MAX_BYTES / MB} MB`;
/** Two decimals, so a file just over the limit never reads as "20.0 MB, over the 20 MB limit". */
const megabytes = (bytes: number) => `${(bytes / MB).toFixed(2)} MB`;
const fileSize = (bytes: number) => (bytes < MB ? `${Math.max(1, Math.round(bytes / 1024))} KB` : megabytes(bytes));

/** Why the browser refuses this file before sending it, or null when the server should see it. */
function rejectReason(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!EXTENSIONS.some((ext) => name.endsWith(ext)))
    return `${file.name} is not a PDF or text file. Choose a .pdf, .txt or .md file.`;
  if (file.size > MAX_BYTES)
    return `${file.name} is ${megabytes(file.size)}, over the ${LIMIT} limit. Choose a smaller file.`;
  return null;
}

/** An upload the server refused (413 too large, 422 unreadable), carrying the server's own message. */
class UploadError extends Error {}

/** The server's message from an error body: a string `detail` from an HTTPException, or FastAPI's validation list. */
function serverMessage(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d as { msg?: unknown }).msg).filter((m): m is string => typeof m === "string");
    return msgs.length ? msgs.join("; ") : null;
  }
  return null;
}

async function uploadReport({ file, title }: { file: File; title: string }): Promise<Report> {
  const form = new FormData();
  form.append("file", file);
  const res = await api
    .POST("/api/reports", {
      // An empty title is left out, so the server names the Report after the file.
      params: { query: title ? { title } : {} },
      body: { file: file.name },
      // The generated body type describes the form fields; the request itself is the multipart form.
      bodySerializer: () => form,
    })
    .catch(() => null);
  if (!res) throw new UploadError("Could not reach the server. Check your connection and try again.");
  if (res.data) return res.data;
  const status = res.response.status;
  const message = serverMessage(res.error);
  if (status === 413) throw new UploadError(`${message ?? "Report file is too large"}. The limit is ${LIMIT}.`);
  if (status === 422) throw new UploadError(`${message ?? "The file could not be read"}.`);
  if (status === 401 || status === 403) throw new UploadError("Your session cannot upload Reports. Sign in again.");
  throw new UploadError(`Upload failed (HTTP ${status}). Try again.`);
}

function UploadReportDialog({ onClose, trigger }: { onClose: () => void; trigger: RefObject<HTMLElement | null> }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const dialog = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const choose = useRef<HTMLButtonElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [rejected, setRejected] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const idPrefix = useId();

  const upload = useMutation({
    mutationFn: uploadReport,
    onSuccess: (report) => {
      // Put the new Report in the cached list first, so its detail renders at once; the refetch then confirms it.
      qc.setQueryData<ReportList>(["reports"], (list) =>
        list ? { ...list, items: [...list.items.filter((r) => r.id !== report.id), report] } : list,
      );
      void qc.invalidateQueries({ queryKey: ["reports"] });
      onClose();
      navigate(reportPath(report.id));
    },
  });
  const busy = upload.isPending;
  const dismiss = () => !busy && onClose();

  useEffect(() => {
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately the trigger at close time
    return () => trigger.current?.focus();
  }, [trigger]);

  // Focus starts on Choose a file. Every control disables while extracting, so focus waits on the dialog rather than
  // fall to the page, and comes back to Choose another file when a refused upload leaves the dialog open.
  useEffect(() => {
    (busy ? dialog : choose).current?.focus();
  }, [busy]);

  // A file dropped anywhere but the drop zone (the backdrop, the title field) would make the browser open it in place
  // of the app, abandoning the dialog and any upload in flight.
  useEffect(() => {
    const swallow = (e: globalThis.DragEvent) => e.preventDefault();
    window.addEventListener("dragover", swallow);
    window.addEventListener("drop", swallow);
    return () => {
      window.removeEventListener("dragover", swallow);
      window.removeEventListener("drop", swallow);
    };
  }, []);

  // Escape closes from anywhere, except while extracting: the request cannot be called back.
  const latestDismiss = useRef(dismiss);
  useEffect(() => {
    latestDismiss.current = dismiss;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && latestDismiss.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pick = (picked: File | undefined) => {
    if (!picked || busy) return;
    upload.reset(); // a new file is a new attempt; the last server error no longer applies
    const reason = rejectReason(picked);
    setRejected(reason);
    setFile(reason ? null : picked);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  };
  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = busy ? "none" : "copy";
    if (!busy) setDragging(true);
  };

  const submit = () => file && !busy && upload.mutate({ file, title: title.trim() });
  const errorMessage = rejected ?? (upload.error ? upload.error.message : null);

  return createPortal(
    <>
      <div className="scrim" onClick={dismiss} />
      <div
        ref={dialog}
        className="run-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${idPrefix}-title`}
        aria-busy={busy}
        tabIndex={-1}
        onKeyDown={(e) => trapTab(e, dialog.current)}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="panel-head !px-4 !py-2.5">
            <h2 id={`${idPrefix}-title`} className="!text-[1.0769rem]">
              Upload Report
            </h2>
            <button
              type="button"
              className="btn btn-ghost btn-sm ml-auto"
              onClick={dismiss}
              disabled={busy}
              aria-label="Close"
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="space-y-3 p-4">
            <div
              className="dropzone"
              data-dragging={dragging || undefined}
              data-busy={busy || undefined}
              onDragEnter={onDragOver}
              onDragOver={onDragOver}
              // Moving over a child fires dragleave too; only leaving the zone itself ends the highlight.
              onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget as Node | null) && setDragging(false)}
              onDrop={onDrop}
            >
              <input
                ref={input}
                type="file"
                accept={ACCEPT}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                disabled={busy}
                onChange={(e) => {
                  pick(e.target.files?.[0]);
                  e.target.value = ""; // picking the same file again after an error still fires
                }}
              />
              {busy ? (
                <p role="status" className="flex items-center gap-2.5 font-semibold text-info">
                  <span className="run-spin" aria-hidden />
                  Extracting Insights from your Report…
                </p>
              ) : file ? (
                <p className="flex min-w-0 items-center gap-2">
                  <Icon name="research" />
                  <span className="min-w-0 truncate font-semibold">{file.name}</span>
                  <span className="mono shrink-0 text-ink-3">{fileSize(file.size)}</span>
                </p>
              ) : (
                <p className="text-ink-2">Drag a PDF or text file here</p>
              )}
              {busy ? (
                <p className="text-ink-3">
                  The LLM is reading <span className="text-ink-2">{file?.name}</span>. This can take a minute; keep this
                  open until it finishes.
                </p>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <button ref={choose} type="button" className="btn btn-sm" onClick={() => input.current?.click()}>
                    {file ? "Choose another file" : "Choose a file"}
                  </button>
                  <span className="text-ink-3">PDF, .txt or .md, up to {LIMIT}</span>
                </div>
              )}
            </div>
            {errorMessage && <ErrorLine>{errorMessage}</ErrorLine>}
            <label className="label" htmlFor={`${idPrefix}-title-field`}>
              Title (optional)
              <input
                id={`${idPrefix}-title-field`}
                className="field w-full"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={file?.name ?? "Defaults to the file name"}
                disabled={busy}
              />
            </label>
          </div>
          <div className="flex justify-end gap-2 border-t border-[rgb(31_38_80/0.08)] px-4 py-2.5">
            <button type="button" className="btn" onClick={dismiss} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={!file || busy}>
              {busy ? "Extracting…" : "Upload and extract"}
            </button>
          </div>
        </form>
      </div>
    </>,
    document.body,
  );
}

/** A button that opens the Upload Report dialog; focus returns to it when the dialog closes. */
export function UploadReportButton({ children, className }: { children: ReactNode; className: string }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={trigger} type="button" className={className} aria-haspopup="dialog" onClick={() => setOpen(true)}>
        {children}
      </button>
      {open && <UploadReportDialog onClose={() => setOpen(false)} trigger={trigger} />}
    </>
  );
}
