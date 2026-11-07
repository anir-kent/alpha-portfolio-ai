/** Insight Review: approve an Insight awaiting review, with an optional note, or reject it with a required note in a
 * small dialog. An Insight Review is final, so the copy says so beside the actions. Report detail and the To review tab
 * share these actions; each chooses where the selection goes once the server confirms. `a` approves and `r` opens the
 * reject dialog: the actions exist only for an Insight awaiting review and a session that may review it, so the
 * shortcuts do too. The server stays the only
 * enforcement point: it answers 409 when another Analyst reviewed the Insight first. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { api } from "./api/client";
import type { Insight, ReportList } from "./research";
import { Kbd, useShortcuts } from "./shortcuts";
import { ErrorLine, Icon, trapTab } from "./ui";

type Action = "approve" | "reject";

/** Another Analyst reviewed the Insight first (409): it is no longer awaiting review. */
class AlreadyReviewed extends Error {}

async function recordReview({ id, action, note }: { id: number; action: Action; note: string | null }) {
  const res = await api
    .POST("/api/insights/{insight_id}/decision", { params: { path: { insight_id: id } }, body: { action, note } })
    .catch(() => null);
  if (!res) throw new Error("Could not reach the server, so the Insight Review was not saved. Try again.");
  if (res.data) return res.data;
  const status = res.response.status;
  if (status === 409) throw new AlreadyReviewed("Already reviewed by someone else");
  if (status === 401 || status === 403) throw new Error("Your session cannot review Insights. Sign in again.");
  if (status === 404) throw new Error("This Insight no longer exists. Reload the page.");
  throw new Error(`The Insight Review was not saved (HTTP ${status}). Try again.`);
}

/** The cached Report list with one Insight replaced by the server's copy, so every count moves at once. */
const withInsight = (list: ReportList, insight: Insight): ReportList => ({
  ...list,
  items: list.items.map((r) =>
    r.id === insight.report_id ? { ...r, insights: r.insights.map((i) => (i.id === insight.id ? insight : i)) } : r,
  ),
});

/** Records Insight Reviews. The callbacks sit on the mutation itself rather than on `mutate`, so they run even when the
 * cache update unmounts the actions first (the last Insight awaiting review turns read-only). `onReviewed` runs before
 * the cache update, so the caller's new selection lands in the same render as the moved counts. */
function useRecordReview({
  onReviewed,
  onFailed,
}: {
  onReviewed: (reviewed: Insight) => void;
  onFailed: (e: Error) => void;
}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: recordReview,
    onSuccess: (insight) => {
      onReviewed(insight);
      qc.setQueryData<ReportList>(["reports"], (list) => (list ? withInsight(list, insight) : list));
      void qc.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (e) => {
      if (e instanceof AlreadyReviewed) void qc.invalidateQueries({ queryKey: ["reports"] });
      onFailed(e);
    },
  });
}

const FINAL_NOTE =
  "An Insight Review is final: it cannot be changed or undone. Approved Insights can inform Research Tilts on Portfolios; rejected ones never do.";

/**
 * Approve and Reject for one Insight awaiting review. Key it on the Insight, so a note or error never carries over to
 * another. `onReviewed` runs once the server confirms; `onAlreadyReviewed` when another Analyst got there first. Either
 * may run after the actions have left the screen, so the caller checks the selection is still this Insight.
 */
export function ReviewActions({
  insight,
  onReviewed,
  onAlreadyReviewed,
}: {
  insight: Insight;
  onReviewed: (reviewed: Insight) => void;
  onAlreadyReviewed: () => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const review = useRecordReview({
    onReviewed,
    onFailed: (e) => {
      setRejecting(false);
      if (e instanceof AlreadyReviewed) onAlreadyReviewed();
    },
  });
  const [noteOpen, setNoteOpen] = useState(false);
  const [approveNote, setApproveNote] = useState("");
  // The reject note outlives the dialog, so a failed save can be retried without typing it again.
  const [rejectNote, setRejectNote] = useState("");
  const rejectButton = useRef<HTMLButtonElement>(null);
  const idPrefix = useId();
  const saving = review.isPending;

  const submit = (action: Action, note: string) => {
    if (saving) return;
    review.mutate({ id: insight.id, action, note: note.trim() || null });
  };
  const approve = () => submit("approve", noteOpen ? approveNote : "");
  const openReject = () => !saving && setRejecting(true);
  useShortcuts({ a: approve, r: openReject });

  const error = review.error && !(review.error instanceof AlreadyReviewed) ? review.error.message : null;
  return (
    <section aria-label="Insight Review" className="space-y-2" aria-busy={saving}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-primary" disabled={saving} aria-keyshortcuts="a" onClick={approve}>
          <Icon name="approvals" size={14} />
          {saving && !rejecting ? (
            "Saving…"
          ) : (
            <>
              Approve <Kbd>A</Kbd>
            </>
          )}
        </button>
        <button
          ref={rejectButton}
          type="button"
          className="btn"
          disabled={saving}
          aria-haspopup="dialog"
          aria-keyshortcuts="r"
          onClick={openReject}
        >
          Reject… <Kbd>R</Kbd>
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          aria-expanded={noteOpen}
          aria-controls={`${idPrefix}-note`}
          disabled={saving}
          onClick={() => setNoteOpen(!noteOpen)}
        >
          <span className={`inline-flex transition-transform ${noteOpen ? "rotate-90" : ""}`} aria-hidden>
            <Icon name="chevron" size={12} />
          </span>
          Approval note (optional)
        </button>
      </div>
      {noteOpen && (
        <label className="label" id={`${idPrefix}-note`}>
          Approval note (optional, recorded with the Insight Review)
          <textarea
            className="field"
            rows={2}
            value={approveNote}
            disabled={saving}
            onChange={(e) => setApproveNote(e.target.value)}
            placeholder="Context for later readers, e.g. consistent with the house view on page 3."
          />
        </label>
      )}
      <p className="flex items-start gap-1.5 text-ink-3">
        <Icon name="lock" size={13} />
        {FINAL_NOTE}
      </p>
      {error && <ErrorLine>{error}</ErrorLine>}
      {rejecting && (
        <RejectDialog
          insight={insight}
          note={rejectNote}
          onNote={setRejectNote}
          saving={saving}
          onSubmit={() => submit("reject", rejectNote)}
          onClose={() => setRejecting(false)}
          trigger={rejectButton}
        />
      )}
    </section>
  );
}

/** Reject with a required note. Focus starts on the note, Tab stays inside, Escape and Cancel close without saving, and
 * focus returns to Reject. While saving nothing can be dismissed: the request cannot be called back. */
function RejectDialog({
  insight,
  note,
  onNote,
  saving,
  onSubmit,
  onClose,
  trigger,
}: {
  insight: Insight;
  note: string;
  onNote: (note: string) => void;
  saving: boolean;
  onSubmit: () => void;
  onClose: () => void;
  trigger: RefObject<HTMLElement | null>;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const idPrefix = useId();
  const dismiss = () => !saving && onClose();
  const missing = note.trim() === "";

  useEffect(() => {
    field.current?.focus();
    // When the review succeeds the actions leave with the dialog, and the detail pane takes focus instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately the trigger at close time
    return () => trigger.current?.focus();
  }, [trigger]);

  // Every control disables while saving, so focus waits on the dialog rather than fall to the page.
  useEffect(() => {
    if (saving) dialog.current?.focus();
  }, [saving]);

  const latestDismiss = useRef(dismiss);
  useEffect(() => {
    latestDismiss.current = dismiss;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && latestDismiss.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return createPortal(
    <>
      <div className="scrim" onClick={dismiss} />
      <div
        ref={dialog}
        className="run-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${idPrefix}-title`}
        aria-describedby={`${idPrefix}-final`}
        aria-busy={saving}
        tabIndex={-1}
        onKeyDown={(e) => trapTab(e, dialog.current)}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!missing) onSubmit();
          }}
        >
          <div className="panel-head !px-4 !py-2.5">
            <h2 id={`${idPrefix}-title`} className="!text-[1.0769rem]">
              Reject Insight
            </h2>
            <button
              type="button"
              className="btn btn-ghost btn-sm ml-auto"
              onClick={dismiss}
              disabled={saving}
              aria-label="Close"
            >
              <Icon name="close" />
            </button>
          </div>
          <div className="space-y-3 p-4">
            <p>
              <span className="font-semibold">{insight.subject}</span>{" "}
              <span className="text-ink-3">
                · cited on page <span className="mono">{insight.page}</span> · Insight{" "}
                <span className="mono">#{insight.id}</span>
              </span>
            </p>
            <label className="label" htmlFor={`${idPrefix}-note`}>
              <span>
                Why is this Insight rejected? <span className="text-neg">(required)</span>
              </span>
              <textarea
                ref={field}
                id={`${idPrefix}-note`}
                className="field"
                rows={3}
                value={note}
                disabled={saving}
                aria-required
                onChange={(e) => onNote(e.target.value)}
                placeholder="Say what is wrong, e.g. the passage is about Utilities, not Energy; or the direction should be negative."
              />
            </label>
            <p id={`${idPrefix}-final`} className="flex items-start gap-1.5 text-ink-3">
              <Icon name="lock" size={13} />
              Rejecting is final. The note is recorded on the audit trail, and a rejected Insight never informs a
              Portfolio.
            </p>
          </div>
          <div className="flex justify-end gap-2 border-t border-[rgb(31_38_80/0.08)] px-4 py-2.5">
            <button type="button" className="btn" onClick={dismiss} disabled={saving} aria-keyshortcuts="Escape">
              Cancel <Kbd>Esc</Kbd>
            </button>
            <button type="submit" className="btn btn-danger" disabled={missing || saving}>
              {saving ? "Saving…" : "Reject Insight"}
            </button>
          </div>
        </form>
      </div>
    </>,
    document.body,
  );
}
