import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { Drawer, ErrorLine, Icon, Pill } from "./ui";

type Detail = components["schemas"]["ExchangeDetail"];
type Verdict = components["schemas"]["GroundingVerdict"];

const TABS = ["Prompt", "Schema", "Reply", "Metadata", "Used by"] as const;
type Tab = (typeof TABS)[number];

/** The Exchange as recorded, hash included. The Audit Events and verdicts that reference it are context, not part of the record. */
export function exchangeRecord(d: Detail): Omit<Detail, "used_by" | "grounding"> {
  const { used_by: _usedBy, grounding: _grounding, ...record } = d;
  return record;
}

/** Save one Exchange as pretty-printed JSON, exactly the fields the API returned. */
export function downloadExchange(d: Detail) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(exchangeRecord(d), null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `llm-exchange-${d.id}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Tokens under either provider's key names; undefined when the call reported none. */
function tokens(usage: Detail["usage"]) {
  const u = (usage ?? {}) as Record<string, unknown>;
  const n = (v: unknown) => (typeof v === "number" ? v : undefined);
  return { input: n(u.prompt_tokens) ?? n(u.input_tokens), output: n(u.completion_tokens) ?? n(u.output_tokens) };
}

/** The Recommendation this Exchange belongs to, from the first referencing event that names one. */
export function recommendationOf(d: Detail): string | null {
  return d.used_by.find((e) => e.recommendation_id)?.recommendation_id ?? null;
}

function Block({ children, label }: { children: ReactNode; label: string }) {
  return (
    <pre tabIndex={0} aria-label={label} className="mono max-h-[28rem] overflow-auto whitespace-pre-wrap break-words rounded-xl border border-line bg-sunken p-2 text-ink">
      {children}
    </pre>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-x-3 border-b border-line py-1.5 last:border-0">
      <dt className="text-ink-3">{label}</dt>
      <dd className="mono min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Claims({ verdicts }: { verdicts: Verdict[] }) {
  if (verdicts.length === 0) return null;
  return (
    <section aria-label="Claims from this reply" className="space-y-2">
      <h3 className="font-semibold">Claims from this reply</h3>
      {verdicts.map((v) => (
        <div key={v.check_id} className="space-y-1">
          <p className="text-ink-2">
            Grounding check <span className="mono">{v.check_id}</span>: {v.summary.grounded} of {v.summary.total} grounded
            {v.summary.ungrounded > 0 && <> · <span className="font-semibold text-neg">{v.summary.ungrounded} ungrounded</span></>}
          </p>
          <ul className="space-y-1">
            {v.claims.map((c) => (
              <li key={c.index} data-grounded={c.grounded} className={`rounded-xl border p-2 ${c.grounded ? "border-line" : "border-neg bg-neg-bg"}`}
                style={c.grounded ? undefined : { boxShadow: "inset 3px 0 var(--color-neg)" }}>
                <div className="flex flex-wrap items-center gap-1">
                  {c.grounded ? <Pill tone="pos">grounded</Pill> : <Pill tone="neg"><Icon name="alert" size={10} />ungrounded</Pill>}
                  {c.asset && <span className="mono text-ink-3">{c.asset}</span>}
                </div>
                <p className="mt-0.5">{c.text}</p>
                {c.issues.map((i) => <p key={i.code + i.message} className="mt-0.5 flex items-center gap-1 text-neg"><Icon name="alert" size={12} />{i.message}</p>)}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

function Body({ d, tab, canLineage }: { d: Detail; tab: Tab; canLineage: boolean }) {
  const t = tokens(d.usage);
  const replayed = d.telemetry === "not_available_replayed";
  const rec = recommendationOf(d);
  switch (tab) {
    case "Prompt":
      return (
        <>
          <h3 className="font-semibold">System text</h3>
          <Block label="System text">{d.system_text}</Block>
          <h3 className="font-semibold">User prompt</h3>
          <Block label="User prompt">{d.user_prompt}</Block>
        </>
      );
    case "Schema":
      return (
        <>
          <p className="text-ink-2">The shape the reply was required to take.</p>
          <Block label="Reply schema">{JSON.stringify(d.reply_schema, null, 2)}</Block>
        </>
      );
    case "Reply":
      return (
        <>
          {d.outcome === "error" && (
            <div role="alert" className="callout callout-neg">
              <p className="font-semibold">This call failed</p>
              <p className="break-words">{d.error ?? "No error text recorded"}</p>
            </div>
          )}
          <h3 className="font-semibold">Raw reply</h3>
          {d.raw_reply === null || d.raw_reply === ""
            ? <p className="text-ink-3">{d.outcome === "error" ? "No reply was captured before the call failed." : "No raw reply recorded."}</p>
            : <Block label="Raw reply">{d.raw_reply}</Block>}
          {d.parsed_content !== null && (
            <>
              <h3 className="font-semibold">Parsed</h3>
              <Block label="Parsed reply">{JSON.stringify(d.parsed_content, null, 2)}</Block>
            </>
          )}
          <Claims verdicts={d.grounding} />
        </>
      );
    case "Metadata":
      return (
        <dl>
          <Field label="Exchange">#{d.id}</Field>
          <Field label="Recorded (UTC)">{d.created_at}</Field>
          <Field label="Task">{d.task}</Field>
          <Field label="Prompt version">{d.prompt_version}</Field>
          <Field label="Model">{d.model ?? "—"}</Field>
          <Field label="Endpoint host">{d.endpoint_host ?? "—"}</Field>
          <Field label="Mode">{d.mode}</Field>
          <Field label="Outcome">{d.outcome}</Field>
          <Field label="Latency">{replayed ? "n/a (replayed)" : d.latency_ms === null ? "—" : `${d.latency_ms.toLocaleString("en-US")} ms`}</Field>
          <Field label="Tokens in">{replayed ? "n/a (replayed)" : t.input?.toLocaleString("en-US") ?? "—"}</Field>
          <Field label="Tokens out">{replayed ? "n/a (replayed)" : t.output?.toLocaleString("en-US") ?? "—"}</Field>
          <Field label="Hash">{d.hash}</Field>
        </dl>
      );
    case "Used by":
      return (
        <>
          {rec && (
            <p>
              {canLineage
                ? <Link className="text-brand hover:underline" to={`/audit/recommendations/${rec}`}>View lineage of Recommendation <span className="mono">#{rec}</span></Link>
                : <>Belongs to Recommendation <span className="mono">#{rec}</span></>}
            </p>
          )}
          {d.used_by.length === 0
            ? <p className="text-ink-3">No Audit Event references this Exchange.</p>
            : (
              <ul className="space-y-1">
                {d.used_by.map((e) => (
                  <li key={e.id} className="rounded-xl border border-line p-2">
                    <span className="font-semibold">{e.type.replace(/_/g, " ")}</span> <span className="mono text-ink-3">event #{e.id}</span>
                    <p className="mono text-[0.7692rem] text-ink-3">{e.timestamp} · {e.actor.name}</p>
                  </li>
                ))}
              </ul>
            )}
          {d.grounding.length === 0
            ? <p className="text-ink-3">No grounding verdict is attached to this Exchange.</p>
            : d.grounding.map((v) => (
              <p key={v.check_id}>
                Grounding verdict <span className="mono">{v.check_id}</span>: {v.summary.grounded} of {v.summary.total} Claims grounded
                {v.summary.ungrounded > 0 && <span className="font-semibold text-neg"> · {v.summary.ungrounded} ungrounded</span>}
              </p>
            ))}
        </>
      );
  }
}

/** Everything recorded about one LLM Exchange. The same drawer opens from the feed and from the lineage graph. */
export function ExchangeDrawer({ id, canLineage, onClose }: { id: number; canLineage: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("Prompt");
  const q = useQuery({
    queryKey: ["llm-exchange", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/llm/exchanges/{exchange_id}", { params: { path: { exchange_id: id } } });
      if (error || !data) throw new Error(`Could not load Exchange #${id}`);
      return data;
    },
  });
  const d = q.data;
  return (
    <Drawer title={`LLM Exchange #${id}`} onClose={onClose}>
      {q.isLoading && <p role="status" className="text-ink-3">Loading Exchange…</p>}
      {q.isError && <ErrorLine>{q.error.message}</ErrorLine>}
      {d && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={d.mode === "live" ? "pos" : "warn"}>{d.mode}</Pill>
            {d.outcome === "error" ? <Pill tone="neg"><Icon name="alert" size={10} />failed</Pill> : <Pill tone="pos">ok</Pill>}
            <span className="mono text-ink-3">{d.task} · {d.prompt_version}</span>
            <button type="button" className="btn btn-sm ml-auto" onClick={() => downloadExchange(d)}>Download JSON</button>
          </div>
          <div role="tablist" aria-label="Exchange sections" className="seg">
            {TABS.map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} aria-pressed={tab === t} onClick={() => setTab(t)}>
                {t}
                {t === "Reply" && d.grounding.some((v) => v.summary.ungrounded > 0) && <span className="ml-1 text-neg" title="This reply produced ungrounded Claims"><Icon name="alert" size={10} /><span className="sr-only"> has ungrounded Claims</span></span>}
              </button>
            ))}
          </div>
          <div role="tabpanel" aria-label={tab} className="space-y-2">
            <Body d={d} tab={tab} canLineage={canLineage} />
          </div>
        </>
      )}
    </Drawer>
  );
}
