import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { createPortal } from "react-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { Icon } from "./ui";

export type RunSnapshot = components["schemas"]["RunSnapshot"];
type Step = RunSnapshot["steps"][number];

const POLL_MS = 1000;
const STREAM_RETRY_MS = 5000; // while polling, how often a successful poll may try the stream again
const SUCCESS = new Set<RunSnapshot["outcome"]>(["completed", "completed_with_warnings"]);

/** The scoring transaction committed: this run's results are current, whatever happened after. */
const recorded = (snap: RunSnapshot) => snap.steps.find((s) => s.key === "record_run")?.outcome === "done";

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

/** connecting/live: stream open · reconnecting: dropped, the browser is reconnecting on its own · unavailable: the stream
 * was refused (any non-200, e.g. the dev proxy's 502 while the API restarts), so the snapshot is polled instead and the
 * stream is tried again once a poll gets through. */
type StreamState = "connecting" | "live" | "reconnecting" | "unavailable";

/**
 * The run's latest snapshot, pushed over the run's event stream (ADR-0005). Each event is the whole snapshot, so the latest
 * one always replaces what is shown, and a reconnect (the browser's own, with Last-Event-ID) needs nothing else. When the
 * stream is unavailable the snapshot is polled until the run has an outcome. `initial` is what the start request returned.
 */
function useRunProgress(initial: RunSnapshot) {
  const runId = initial.run_id;
  const [snap, setSnap] = useState(initial);
  const [stream, setStream] = useState<StreamState>("connecting");
  const [pollFailed, setPollFailed] = useState(false);
  const [attempt, setAttempt] = useState(0); // bumping it reopens the stream
  const opened = useRef(0);
  const finished = snap.outcome != null;

  useEffect(() => {
    opened.current = Date.now();
    setStream("connecting"); // eslint-disable-line react-hooks/set-state-in-effect -- resetting the connection state is part of (re)subscribing
    const es = new EventSource(`/api/analysis/runs/${runId}/events`, { withCredentials: true });
    es.onopen = () => setStream("live");
    es.addEventListener("progress", (e) => {
      let next: RunSnapshot;
      try {
        next = JSON.parse((e as MessageEvent).data) as RunSnapshot;
      } catch {
        return;
      } // the next event carries it all again
      setSnap(next);
      setStream("live");
      if (next.outcome) es.close(); // final: the server closes too, and the browser must not reconnect
    });
    es.onerror = () => setStream(es.readyState === EventSource.CLOSED ? "unavailable" : "reconnecting"); // CLOSED: refused (401/403/404) or no retry coming
    return () => es.close();
  }, [runId, attempt]);

  useEffect(() => {
    // the fallback: poll the snapshot while the stream is unavailable and the run goes on
    if (stream !== "unavailable" || finished) return;
    let stopped = false;
    const poll = async () => {
      const { data } = await api
        .GET("/api/analysis/runs/{run_id}", { params: { path: { run_id: runId } } })
        .catch(() => ({ data: undefined }));
      if (stopped) return;
      setPollFailed(!data);
      if (!data) return;
      setSnap(data);
      if (!data.outcome && Date.now() - opened.current >= STREAM_RETRY_MS) setAttempt((a) => a + 1); // the server is back: go live again
    };
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, [stream, finished, runId]);

  return { snap, stream, pollFailed };
}

const STREAM_NOTE: Record<StreamState, string | null> = {
  connecting: "Connecting…",
  live: null,
  reconnecting: "Reconnecting… progress may be briefly behind.",
  unavailable: `Live updates unavailable; checking every ${POLL_MS / 1000}s.`,
};

function StepIcon({ outcome }: { outcome: Step["outcome"] }) {
  if (outcome === "running") return <span className="run-spin" aria-hidden="true" />;
  const glyph = { pending: null, done: "approvals", failed: "alert", skipped: null }[outcome];
  return (
    <span className={`run-dot run-dot-${outcome}`} aria-hidden="true">
      {glyph ? <Icon name={glyph} size={11} /> : outcome === "skipped" ? "–" : null}
    </span>
  );
}

/** Inside the live region only outcome changes are read out: the ticking timer and the n/N count are hidden from it.
 * `inlineError` shows a failed step's message under it; a Failed run says it once, below the list, instead. */
function StepRow({ step, now, inlineError }: { step: Step; now: number; inlineError: boolean }) {
  const time =
    step.started_at && step.finished_at
      ? duration(step.started_at, step.finished_at)
      : step.outcome === "running" && step.started_at
        ? duration(step.started_at, now)
        : null;
  const count = step.total != null ? `${step.done ?? 0}/${step.total}` : null;
  return (
    <li className={`run-step run-step-${step.outcome}`}>
      <StepIcon outcome={step.outcome} />
      <span className="flex-1">
        {step.label}
        {count && (
          <span className="mono ml-2 text-ink-3" aria-hidden="true">
            {count}
          </span>
        )}
        <span className="sr-only">: {step.outcome}</span>
        {inlineError && step.outcome === "failed" && step.error && (
          <span className="block font-normal text-neg">{step.error}</span>
        )}
      </span>
      {step.outcome === "skipped" ? (
        <span className="text-ink-3">skipped</span>
      ) : (
        time && (
          <span className="mono text-ink-3" aria-hidden={step.outcome === "running"}>
            {time}
          </span>
        )
      )}
    </li>
  );
}

const HEADLINE: Record<NonNullable<RunSnapshot["outcome"]>, string> = {
  completed: "Completed",
  completed_with_warnings: "Completed with warnings",
  failed: "Failed",
  interrupted: "Interrupted",
};

/** What a Failed run tells the user: the failed Run Step, that nothing changed, and a reference for the server log. */
function failedMessage(snap: RunSnapshot): string {
  const step = snap.steps.find((s) => s.outcome === "failed");
  return `${step?.label ?? "The run"} failed. The Queue still shows the previous run. Reference: run #${snap.run_id}`;
}

/** What an Interrupted run (the server restarted mid-run) tells the user. Its scoring either never committed, so nothing
 * changed, or committed before the restart, so its results stand without some narratives. */
function interruptedMessage(snap: RunSnapshot): string {
  return recorded(snap)
    ? "Run interrupted after its results were recorded. The Queue now shows this run; some narratives may be missing."
    : "Run interrupted. The Queue still shows the previous run";
}

/**
 * Follows one Analysis Run's Run Steps (ADR-0005). An accessible dialog: focus moves in on open and back to the trigger on
 * close, Tab stays inside, Escape hides it. Closing never stops the run. On a successful outcome the Queue and
 * Recommendation views are refreshed.
 */
export function RunAnalysisModal({
  initial,
  onClose,
  trigger,
}: {
  initial: RunSnapshot;
  onClose: () => void;
  trigger: RefObject<HTMLElement | null>;
}) {
  const qc = useQueryClient();
  const { snap, stream, pollFailed } = useRunProgress(initial);
  const finished = snap.outcome != null;
  const now = useNow(!finished);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately the trigger at close time
    return () => trigger.current?.focus(); // the trigger, not whatever had focus: it was disabled while the run started
  }, [trigger]);

  const resultsChanged = SUCCESS.has(snap.outcome) || (snap.outcome === "interrupted" && recorded(snap)); // an Interrupted
  // run refreshes nothing, unless its results were recorded before the restart
  useEffect(() => {
    if (!resultsChanged) return;
    qc.invalidateQueries({ queryKey: ["queue"] });
    qc.invalidateQueries({ queryKey: ["portfolio"] }); // each Portfolio view carries its Recommendation
  }, [resultsChanged, qc]);

  useEffect(() => {
    // Escape hides it wherever focus is, like the Drawer
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onKeyDown = (e: ReactKeyboardEvent) => {
    // Tab stays inside
    if (e.key !== "Tab" || !dialog.current) return;
    const focusable = [
      ...dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      ),
    ];
    if (focusable.length === 0) return e.preventDefault();
    const first = focusable[0],
      last = focusable[focusable.length - 1];
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
        ref={dialog}
        className="run-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="run-modal-title"
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <div className="panel-head !px-4 !py-2.5">
          <h2 id="run-modal-title" className="!text-[1.0769rem]">
            Analysis run <span className="mono text-ink-3">#{snap.run_id}</span>
          </h2>
          <span className="mono ml-auto text-ink-3" aria-label={`Total time ${total}`}>
            {total}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        <div className="space-y-3 p-4">
          <ol className="space-y-1" aria-live="polite" aria-label="Run Steps">
            {snap.steps.map((s) => (
              <StepRow key={s.key} step={s} now={now} inlineError={snap.outcome !== "failed"} />
            ))}
          </ol>
          <p role="status" className={finished ? "font-semibold" : "text-ink-3"}>
            {snap.outcome ? HEADLINE[snap.outcome] : "Running… You can close this; the run carries on."}
          </p>
          {snap.outcome === "failed" && <p className="text-neg">{failedMessage(snap)}</p>}
          {snap.outcome === "interrupted" && <p className="text-neg">{interruptedMessage(snap)}</p>}
          {!finished && STREAM_NOTE[stream] && (
            <p className="text-ink-3">
              {pollFailed ? "Could not load the run's progress. Retrying…" : STREAM_NOTE[stream]}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-[rgb(31_38_80/0.08)] px-4 py-2.5">
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
          {SUCCESS.has(snap.outcome) && (
            <button type="button" className="btn btn-primary" onClick={onClose}>
              View updated queue
            </button>
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}
