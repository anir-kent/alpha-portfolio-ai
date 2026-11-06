import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import { ExchangeDrawer } from "./ExchangeDrawer";
import type { components } from "./api/schema";
import { Empty, ErrorLine, Icon, PageHeader, Panel, Pill } from "./ui";

type Exchange = components["schemas"]["ExchangeSummary"];
type Filters = { task: string; prompt_version: string; mode: "" | "live" | "recorded"; outcome: "" | "ok" | "error"; date_from: string; date_to: string };
/** idle: tail off · connecting/live: stream open · reconnecting: dropped, the browser is resuming from the last id · unavailable: gave up, the list is authoritative. */
type StreamState = "idle" | "connecting" | "live" | "reconnecting" | "unavailable";

const EMPTY: Filters = { task: "", prompt_version: "", mode: "", outcome: "", date_from: "", date_to: "" };
const TASKS = ["insight_extraction", "research_tilt", "recommendation_narrative", "priority_narrative"];
const PAGE = 50;
const STREAM_URL = "/api/llm/exchanges/stream";

const toIso = (local: string) => (local ? new Date(local).toISOString() : undefined);
/** A datetime-local value has minute precision; as an upper bound it must cover the whole minute. */
const toIsoEnd = (local: string) => (local ? new Date(new Date(local).getTime() + 59_999).toISOString() : undefined);
const NA = "n/a (replayed)";

/** Prompt/completion tokens under either provider's key names; undefined when the call reported none. */
export function tokenCounts(usage: Exchange["usage"]): { input?: number; output?: number } {
  const u = (usage ?? {}) as Record<string, unknown>;
  const n = (v: unknown) => (typeof v === "number" ? v : undefined);
  return { input: n(u.prompt_tokens) ?? n(u.input_tokens), output: n(u.completion_tokens) ?? n(u.output_tokens) };
}

/** Whether a streamed row belongs in the current filtered view (the stream itself is unfiltered). */
export function matches(x: Exchange, f: Filters): boolean {
  const t = Date.parse(x.created_at);
  return (!f.task || x.task === f.task)
    && (!f.prompt_version || x.prompt_version === f.prompt_version)
    && (!f.mode || x.mode === f.mode)
    && (!f.outcome || x.outcome === f.outcome)
    && (!f.date_from || t >= Date.parse(toIso(f.date_from)!))
    && (!f.date_to || t <= Date.parse(toIsoEnd(f.date_to)!));
}

/** Streamed rows over the fetched page, de-duplicated by id, newest first. Fetched data wins: it is the same row, settled. */
export function mergeRows(live: Exchange[], fetched: Exchange[]): Exchange[] {
  const byId = new Map<number, Exchange>();
  for (const x of live) byId.set(x.id, x);
  for (const x of fetched) byId.set(x.id, x);
  return [...byId.values()].sort((a, b) => b.id - a.id);
}

function useLiveTail(enabled: boolean, onRow: (x: Exchange) => void, onDrop: () => void, onOpen: () => void): StreamState {
  const [state, setState] = useState<StreamState>("idle");
  const handlers = useRef({ onRow, onDrop, onOpen });
  useLayoutEffect(() => { handlers.current = { onRow, onDrop, onOpen }; }); // the open connection always calls the latest filters, not those at connect time
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting the connection state is part of (re)subscribing
    if (!enabled) { setState("idle"); return; }
    setState("connecting");
    // The browser resends Last-Event-ID itself when it reconnects, so a dropped connection resumes without gaps or repeats.
    const es = new EventSource(STREAM_URL, { withCredentials: true });
    es.onopen = () => { setState("live"); handlers.current.onOpen(); }; // a fresh connection starts at the tail: refetch to cover the gap
    es.addEventListener("exchange", (e) => {
      try { handlers.current.onRow(JSON.parse((e as MessageEvent).data) as Exchange); } catch { /* a malformed event is skipped, the list still has the row */ }
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) { setState("unavailable"); handlers.current.onDrop(); } // refused (403/401) or server gone: no retry coming
      else setState("reconnecting");
    };
    return () => es.close();
  }, [enabled]);
  return state;
}

const STATE_PILL: Record<StreamState, { tone: "mute" | "pos" | "warn" | "info"; text: string; hint: string }> = {
  idle: { tone: "mute", text: "Live tail off", hint: "New Exchanges appear when you reload or search again" },
  connecting: { tone: "info", text: "Connecting…", hint: "Opening the stream" },
  live: { tone: "pos", text: "Streaming", hint: "New Exchanges appear as they complete" },
  reconnecting: { tone: "warn", text: "Reconnecting…", hint: "The connection dropped; resuming from the last Exchange seen" },
  unavailable: { tone: "warn", text: "Stream unavailable, showing list", hint: "The live stream could not be kept open; the list below is still current as of the last refresh" },
};

function Figure({ value, replayed }: { value: number | undefined; replayed: boolean }) {
  if (replayed) return <span className="text-ink-3">{NA}</span>;
  return <>{value === undefined ? "—" : value.toLocaleString("en-US")}</>;
}

function Linked({ x, canLineage, canPortfolio }: { x: Exchange; canLineage: boolean; canPortfolio: boolean }) {
  if (!x.recommendation_id && !x.portfolio_id) return <span className="text-ink-3">—</span>;
  return (
    <span className="flex flex-col">
      {x.recommendation_id && (canLineage
        ? <Link className="text-brand hover:underline" to={`/audit/recommendations/${x.recommendation_id}`}>Recommendation <span className="mono">#{x.recommendation_id}</span></Link>
        : <span>Recommendation <span className="mono">#{x.recommendation_id}</span></span>)}
      {x.portfolio_id && (canPortfolio
        ? <Link className="text-brand hover:underline" to={`/portfolios/${x.portfolio_id}`}>Portfolio <span className="mono">{x.portfolio_id}</span></Link>
        : <span>Portfolio <span className="mono">{x.portfolio_id}</span></span>)}
    </span>
  );
}

export function ExchangesPage({ permissions }: { permissions: string[] }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [limit, setLimit] = useState(PAGE);
  const [tail, setTail] = useState(false);
  const [live, setLive] = useState<Exchange[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);

  const listKey = ["llm-exchanges", applied, limit] as const;
  const list = useQuery({
    queryKey: listKey,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/llm/exchanges", {
        params: { query: {
          task: applied.task || undefined, prompt_version: applied.prompt_version || undefined,
          mode: applied.mode || undefined, outcome: applied.outcome || undefined,
          date_from: toIso(applied.date_from), date_to: toIsoEnd(applied.date_to), limit,
        } },
      });
      if (error || !data) throw new Error("Could not load LLM Exchanges");
      return data;
    },
  });

  // Streamed rows are kept in page state, not the query cache, so turning the tail off or losing the stream never drops them.
  const state = useLiveTail(
    tail,
    (x) => { if (matches(x, applied)) setLive((rows) => (rows.some((r) => r.id === x.id) ? rows : [x, ...rows])); },
    () => qc.invalidateQueries({ queryKey: ["llm-exchanges"] }), // stream lost: refetch the list; streamed rows stay on screen
    () => qc.invalidateQueries({ queryKey: ["llm-exchanges"] }),
  );
  const toggleTail = () => {
    if (tail) qc.invalidateQueries({ queryKey: ["llm-exchanges"] }); // turning off: catch up on whatever arrived meanwhile
    setTail(!tail);
  };

  const rows = useMemo(() => mergeRows(live, list.data?.items ?? []), [live, list.data]);
  const total = list.data ? Math.max(list.data.total, rows.length) : rows.length;
  const pill = STATE_PILL[state];

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value } as Filters);
  const apply = (next: Filters) => { setApplied(next); setLive([]); setLimit(PAGE); };
  const pick = <K extends "mode" | "outcome">(k: K, v: Filters[K]) => { const next = { ...form, [k]: v }; setForm(next); apply(next); };

  const canLineage = permissions.includes("audit:read");
  const canPortfolio = permissions.includes("portfolio:read");

  return (
    <div>
      <PageHeader
        title="LLM Exchanges"
        sub="Every prompt sent to the model and every reply, as recorded. Newest first."
        actions={
          <>
            <span role="status" aria-live="polite"><Pill tone={pill.tone} title={pill.hint}>
              {state === "live" && <span aria-hidden className="size-1.5 rounded-full bg-pos shadow-[0_0_6px_#2fb67a]" />}{pill.text}
            </Pill></span>
            <button type="button" className={`btn ${tail ? "btn-primary" : ""}`} aria-pressed={tail} onClick={toggleTail}>
              <Icon name="spark" size={13} />Live tail
            </button>
          </>
        }
      />

      <form className="panel mb-3 flex flex-wrap items-end gap-x-4 gap-y-2 px-3 py-2" role="search" aria-label="Exchange filters"
        onSubmit={(e) => { e.preventDefault(); apply(form); }}>
        <label className="label">Task
          <select className="field" value={form.task} onChange={set("task")}>
            <option value="">All</option>
            {TASKS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="label">Prompt version
          <input className="field w-44" value={form.prompt_version} onChange={set("prompt_version")} placeholder="e.g. insight_extraction@v1" />
        </label>
        <div className="label">Mode
          <div className="seg" role="group" aria-label="Mode">
            {([["", "All"], ["live", "Live"], ["recorded", "Recorded"]] as const).map(([v, l]) => (
              <button key={v} type="button" aria-pressed={form.mode === v} onClick={() => pick("mode", v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="label">Outcome
          <div className="seg" role="group" aria-label="Outcome">
            {([["", "All"], ["ok", "OK"], ["error", "Failed"]] as const).map(([v, l]) => (
              <button key={v} type="button" aria-pressed={form.outcome === v} onClick={() => pick("outcome", v)}>{l}</button>
            ))}
          </div>
        </div>
        <label className="label">From
          <input type="datetime-local" className="field" value={form.date_from} onChange={set("date_from")} />
        </label>
        <label className="label">To
          <input type="datetime-local" className="field" value={form.date_to} onChange={set("date_to")} />
        </label>
        <button className="btn btn-primary">Search</button>
        <button type="button" className="btn btn-ghost" onClick={() => { setForm(EMPTY); apply(EMPTY); }}>Clear</button>
      </form>

      {list.isError && <ErrorLine>{list.error.message}</ErrorLine>}
      {list.isLoading && <p role="status" className="px-1 py-2 text-ink-3">Loading Exchanges…</p>}
      {(list.data || rows.length > 0) && (
        <Panel
          title="Exchanges"
          aside={<>Showing <span className="mono">{rows.length}</span> of <span className="mono">{total}</span>, newest first</>}
          flush
        >
          <table className="grid-table">
            <thead><tr>
              <th className="num">#</th><th>Time (UTC)</th><th>Task</th><th>Prompt version</th><th>Model</th><th>Mode</th><th>Outcome</th>
              <th className="num">Latency</th><th className="num">Tokens in</th><th className="num">Tokens out</th><th>Used by</th>
            </tr></thead>
            <tbody>
              {rows.map((x) => {
                const replayed = x.telemetry === "not_available_replayed";
                const failed = x.outcome === "error";
                const t = tokenCounts(x.usage);
                return (
                  <tr key={x.id} style={{ boxShadow: failed ? "inset 3px 0 var(--color-neg)" : undefined }} className={`cursor-pointer ${failed ? "!bg-neg-bg" : ""}`}
                    onClick={(e) => { if (!(e.target as HTMLElement).closest("a, button")) setOpenId(x.id); }}>
                    <td className="num">
                      <button type="button" className="mono text-brand hover:underline" aria-label={`Open Exchange ${x.id}`} onClick={() => setOpenId(x.id)}>{x.id}</button>
                    </td>
                    <td className="mono whitespace-nowrap">{x.created_at}</td>
                    <td className="mono">{x.task}</td>
                    <td className="mono">{x.prompt_version}</td>
                    <td className="mono">{x.model ?? "—"}</td>
                    <td><Pill tone={x.mode === "live" ? "pos" : "warn"} title={x.mode === "live" ? "Sent to the live endpoint" : "Replayed from a committed recording"}>{x.mode}</Pill></td>
                    <td>
                      {failed
                        ? <><Pill tone="neg"><Icon name="alert" size={10} />failed</Pill><span className="mt-1 block max-w-xs break-words text-[0.8461rem] text-neg">{x.error ?? "No error text recorded"}</span></>
                        : <Pill tone="pos">ok</Pill>}
                    </td>
                    <td className="num">{replayed ? <Figure value={undefined} replayed /> : x.latency_ms === null ? "—" : <>{x.latency_ms.toLocaleString("en-US")} ms</>}</td>
                    <td className="num"><Figure value={t.input} replayed={replayed} /></td>
                    <td className="num"><Figure value={t.output} replayed={replayed} /></td>
                    <td><Linked x={x} canLineage={canLineage} canPortfolio={canPortfolio} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <Empty>{JSON.stringify(applied) === JSON.stringify(EMPTY) ? "No LLM Exchanges recorded yet. Run an analysis and they will appear here." : "No Exchanges match these filters."}</Empty>}
          {list.data && list.data.items.length < list.data.total && (
            <div className="px-3 py-2"><button type="button" className="btn btn-sm" onClick={() => setLimit(limit + PAGE)} disabled={list.isFetching}>Show more</button></div>
          )}
        </Panel>
      )}
      {openId !== null && <ExchangeDrawer id={openId} canLineage={canLineage} onClose={() => setOpenId(null)} />}
    </div>
  );
}
