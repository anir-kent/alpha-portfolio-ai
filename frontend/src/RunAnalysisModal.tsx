import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { createPortal } from "react-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { Icon } from "./ui";

export type RunSnapshot = components["schemas"]["RunSnapshot"];
type Step = RunSnapshot["steps"][number];

const POLL_MS = 1000;
const SUCCESS = new Set<RunSnapshot["outcome"]>(["completed", "completed_with_warnings"]);

/** Server timestamps carry microseconds; Date wants milliseconds at most. */
const ms = (ts: string) => Date.parse(ts.replace(/(\.\d{3})\d+/, "$1"));

function duration(from: string, to: string | number) {
  const s = Math.max(0, ((typeof to === "number" ? to : ms(to)) - ms(from)) / 1000);
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
}

/** Re-renders every second while `on`, for the running timers. */
function useNow(on: boolean) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [on]);
  return now;
}

/** The run's snapshot, polled until it has an outcome. `initial` is what the start request returned. */
function useRunSnapshot(initial: RunSnapshot) {
  return useQuery({
    queryKey: ["analysis-run", initial.run_id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/analysis/runs/{run_id}", { params: { path: { run_id: initial.run_id } } });
      if (error || !data) throw new Error("Could not load the run's progress");
      return data;
    },
    initialData: initial,
    initialDataUpdatedAt: 0, // fetch at once: the start response is already behind
    refetchInterval: (q) => (q.state.data?.outcome ? false : POLL_MS),
  });
}

function StepIcon({ outcome }: { outcome: Step["outcome"] }) {
  if (outcome === "running") return <span className="run-spin" aria-hidden="true" />;
  const glyph = { pending: null, done: "approvals", failed: "alert", skipped: null }[outcome];
  return (
    <span className={`run-dot run-dot-${outcome}`} aria-hidden="true">
      {glyph ? <Icon name={glyph} size={11} /> : outcome === "skipped" ? "–" : null}
    </span>
  );
}

/** Inside the live region only outcome changes are read out: the ticking timer and the n/N count are hidden from it. */
function StepRow({ step, now }: { step: Step; now: number }) {
  const time = step.started_at && step.finished_at ? duration(step.started_at, step.finished_at)
    : step.outcome === "running" && step.started_at ? duration(step.started_at, now) : null;
  const count = step.total != null ? `${step.done ?? 0}/${step.total}` : null;
  return (
    <li className={`run-step run-step-${step.outcome}`}>
      <StepIcon outcome={step.outcome} />
      <span className="flex-1">
        {step.label}
        {count && <span className="mono ml-2 text-ink-3" aria-hidden="true">{count}</span>}
        <span className="sr-only">: {step.outcome}</span>
      </span>
      {step.outcome === "skipped" ? <span className="text-ink-3">skipped</span>
        : time && <span className="mono text-ink-3" aria-hidden={step.outcome === "running"}>{time}</span>}
    </li>
  );
}

const HEADLINE: Record<NonNullable<RunSnapshot["outcome"]>, string> = {
  completed: "Completed", completed_with_warnings: "Completed with warnings", failed: "Failed", interrupted: "Interrupted",
};

/**
 * Follows one Analysis Run's Run Steps (ADR-0005). An accessible dialog: focus moves in on open and back to the trigger on
 * close, Tab stays inside, Escape hides it. Closing never stops the run. On a successful outcome the Queue and
 * Recommendation views are refreshed.
 */
export function RunAnalysisModal({ initial, onClose, trigger }: { initial: RunSnapshot; onClose: () => void; trigger: RefObject<HTMLElement | null> }) {
  const qc = useQueryClient();
  const run = useRunSnapshot(initial);
  const snap = run.data;
  const finished = snap.outcome != null;
  const now = useNow(!finished);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
    return () => trigger.current?.focus(); // the trigger, not whatever had focus: it was disabled while the run started
  }, [trigger]);

  useEffect(() => {
    if (!SUCCESS.has(snap.outcome)) return;
    qc.invalidateQueries({ queryKey: ["queue"] });
    qc.invalidateQueries({ queryKey: ["portfolio"] }); // each Portfolio view carries its Recommendation
  }, [snap.outcome, qc]);

  useEffect(() => { // Escape hides it wherever focus is, like the Drawer
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onKeyDown = (e: ReactKeyboardEvent) => { // Tab stays inside
    if (e.key !== "Tab" || !dialog.current) return;
    const focusable = [...dialog.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])")];
    if (focusable.length === 0) return e.preventDefault();
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const total = duration(snap.started_at, snap.finished_at ?? now);
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <div
        ref={dialog} className="run-modal" role="dialog" aria-modal="true" aria-labelledby="run-modal-title" tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <div className="panel-head !px-4 !py-2.5">
          <h2 id="run-modal-title" className="!text-[1.0769rem]">Analysis run <span className="mono text-ink-3">#{snap.run_id}</span></h2>
          <span className="mono ml-auto text-ink-3" aria-label={`Total time ${total}`}>{total}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </div>
        <div className="space-y-3 p-4">
          <ol className="space-y-1" aria-live="polite" aria-label="Run Steps">
            {snap.steps.map((s) => <StepRow key={s.key} step={s} now={now} />)}
          </ol>
          <p role="status" className={finished ? "font-semibold" : "text-ink-3"}>
            {snap.outcome ? HEADLINE[snap.outcome] : "Running… You can close this; the run carries on."}
          </p>
          {run.isError && <p className="text-ink-3">Progress is out of date: {run.error.message}. Retrying…</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-[rgb(31_38_80/0.08)] px-4 py-2.5">
          <button type="button" className="btn" onClick={onClose}>Close</button>
          {SUCCESS.has(snap.outcome) && <button type="button" className="btn btn-primary" onClick={onClose}>View updated queue</button>}
        </div>
      </div>
    </>,
    document.body,
  );
}
