import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import type { operations } from "./api/schema";
import { Empty, ErrorLine, Icon, PageHeader, Panel, Pill } from "./ui";

type EventType = NonNullable<operations["searchAuditEvents"]["parameters"]["query"]>["type"];
type Filters = Record<"type" | "actor" | "portfolio_id" | "client_id" | "recommendation_id" | "report_id" | "date_from" | "date_to", string>;

const EMPTY: Filters = { type: "", actor: "", portfolio_id: "", client_id: "", recommendation_id: "", report_id: "", date_from: "", date_to: "" };
const FIELDS: [keyof Filters, string][] = [
  ["actor", "Actor"], ["portfolio_id", "Portfolio"], ["client_id", "Client"],
  ["recommendation_id", "Recommendation"], ["report_id", "Report"],
];
const EVENT_TYPES = [
  "report_ingested", "insight_extracted", "insight_approved", "analysis_run_started", "priority_scored",
  "suitability_evaluated", "recommendation_drafted", "memo_generated", "recommendation_modified", "recommendation_superseded",
  "decision_recorded", "exception_approved", "exception_blocked", "adversarial_fixtures_run", "access_denied",
];
const OVERRIDES = new Set(["recommendation_modified", "exception_approved"]);

const toIso = (local: string) => (local ? new Date(local).toISOString() : undefined);

export function VerifyPanel() {
  const verify = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.GET("/api/audit/verify");
      if (error || !data) throw new Error("Verification request failed");
      return data;
    },
  });
  const v = verify.data;
  return (
    <section className="panel mb-3 flex flex-wrap items-center gap-3 px-3 py-2" aria-label="Chain verification">
      <span className="grid size-7 place-items-center rounded-full" style={{ background: !v ? "var(--color-sunken)" : v.valid ? "var(--color-pos-bg)" : "var(--color-neg-bg)", color: !v ? "var(--color-ink-3)" : v.valid ? "var(--color-pos)" : "var(--color-neg)" }}>
        <Icon name={v && !v.valid ? "alert" : "audit"} size={16} />
      </span>
      <div className="min-w-0">
        <p className="font-semibold">Hash-chain integrity</p>
        <p className="text-ink-2">Each event stores the hash of the one before it; any edit breaks every link after it.</p>
      </div>
      <div className="ml-auto flex items-center gap-3">
        {!v && !verify.isPending && <Pill tone="mute">Not verified this session</Pill>}
        {verify.isPending && <Pill tone="info">Verifying…</Pill>}
        {v?.valid && <span role="status"><Pill tone="pos"><Icon name="approvals" size={11} />Chain intact</Pill> <span className="mono text-ink-2">{v.checked} events verified</span></span>}
        <button className="btn btn-primary" onClick={() => verify.mutate()} disabled={verify.isPending}>Verify chain</button>
      </div>
      {verify.isError && <div className="w-full"><ErrorLine>{verify.error.message}</ErrorLine></div>}
      {v && !v.valid && (
        <p role="alert" className="callout callout-neg w-full">
          <Icon name="alert" size={16} />
          <span><strong>Tampered link.</strong> Chain broken at event <span className="mono">#{v.first_broken_id}</span>: {v.reason} (<span className="mono">{v.checked}</span> events verified before the break).</span>
        </p>
      )}
    </section>
  );
}

export function AuditPage() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const results = useQuery({
    queryKey: ["audit-events", applied],
    queryFn: async () => {
      const query = {
        type: (applied.type || undefined) as EventType,
        actor: applied.actor || undefined,
        portfolio_id: applied.portfolio_id || undefined,
        client_id: applied.client_id || undefined,
        recommendation_id: applied.recommendation_id || undefined,
        report_id: applied.report_id || undefined,
        date_from: toIso(applied.date_from),
        date_to: toIso(applied.date_to),
        limit: 200,
      };
      const { data, error } = await api.GET("/api/audit/events", { params: { query } });
      if (error || !data) throw new Error("Search failed");
      return data;
    },
  });
  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div>
      <PageHeader title="Audit" sub="Append-only, hash-chained record of every AI output, rule result and human decision." />
      <VerifyPanel />
      <form className="panel mb-3 flex flex-wrap items-end gap-x-3 gap-y-2 px-3 py-2" role="search" onSubmit={(e) => { e.preventDefault(); setApplied(form); }}>
        <label className="label">Event type
          <select className="field" value={form.type} onChange={set("type")}>
            <option value="">All</option>
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        {FIELDS.map(([k, label]) => (
          <label key={k} className="label">{label}
            <input className="field w-32" value={form[k]} onChange={set(k)} />
          </label>
        ))}
        <label className="label">From
          <input type="datetime-local" className="field" value={form.date_from} onChange={set("date_from")} />
        </label>
        <label className="label">To
          <input type="datetime-local" className="field" value={form.date_to} onChange={set("date_to")} />
        </label>
        <button className="btn btn-primary">Search</button>
        <button type="button" className="btn btn-ghost" onClick={() => { setForm(EMPTY); setApplied(EMPTY); }}>Clear</button>
      </form>
      {results.isError && <ErrorLine>{results.error.message}</ErrorLine>}
      {results.data && (
        <Panel
          title="Events"
          aside={<>Showing <span className="mono">{results.data.items.length}</span> of <span className="mono">{results.data.total}</span>, newest first</>}
          flush
        >
          <table className="grid-table">
            <thead><tr>
              <th className="num">#</th><th>Time (UTC)</th><th>Type</th><th>Actor</th><th>Parents</th><th>Payload</th>
            </tr></thead>
            <tbody>
              {results.data.items.map((e) => {
                const denied = e.type === "access_denied";
                const override = OVERRIDES.has(e.type) || (e.type === "decision_recorded" && (e.payload as { action?: string }).action === "modify");
                return (
                  <tr key={e.id} className={denied ? "!bg-neg-bg" : override ? "!bg-warn-bg" : ""} style={{ boxShadow: denied ? "inset 3px 0 var(--color-neg)" : override ? "inset 3px 0 #d99a2b" : undefined }}>
                    <td className="num">
                      {e.id}
                      {e.recommendation_id && <Link className="block text-[0.7692rem] text-brand hover:underline" to={`/audit/recommendations/${e.recommendation_id}`}>Lineage</Link>}
                    </td>
                    <td className="mono whitespace-nowrap">{e.timestamp}</td>
                    <td>
                      <span className="mono">{e.type}</span>
                      {denied && <> <Pill tone="neg"><Icon name="lock" size={10} />security</Pill></>}
                      {override && <> <Pill tone="warn">override</Pill></>}
                    </td>
                    <td>
                      {e.actor.name}
                      {e.actor.role && <span className="text-ink-3"> ({e.actor.role})</span>}
                      {e.actor.model && <span className="block"><Pill tone="ai"><Icon name="spark" size={10} />{e.actor.model}</Pill> <span className="mono text-ink-3">{e.actor.prompt_version}</span></span>}
                    </td>
                    <td className="mono">{e.parent_ids.join(", ") || "—"}</td>
                    <td className="max-w-md">
                      <details>
                        <summary className="cursor-pointer truncate text-ink-3">{JSON.stringify(e.payload).slice(0, 70)}…</summary>
                        <pre className="mono mt-1 overflow-x-auto whitespace-pre-wrap break-all text-[0.8461rem]">{JSON.stringify(e.payload, null, 2)}</pre>
                      </details>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {results.data.items.length === 0 && <Empty>No events match.</Empty>}
        </Panel>
      )}
    </div>
  );
}
