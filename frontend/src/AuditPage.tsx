import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api/client";
import type { operations } from "./api/schema";

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
  "decision_recorded", "exception_approved", "exception_blocked", "access_denied",
];

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
    <section className="mb-6 rounded border p-4" aria-label="Chain verification">
      <button className="rounded bg-slate-800 px-3 py-1 text-white" onClick={() => verify.mutate()} disabled={verify.isPending}>
        Verify chain
      </button>
      {verify.isError && <p className="mt-2 text-red-600">{verify.error.message}</p>}
      {v && (v.valid
        ? <p role="status" className="mt-2 text-green-700">Chain intact: {v.checked} events verified.</p>
        : <p role="alert" className="mt-2 text-red-700">
            Chain broken at event #{v.first_broken_id}: {v.reason} ({v.checked} events verified before the break).
          </p>)}
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
      <h1 className="mb-4 text-xl font-semibold">Audit</h1>
      <VerifyPanel />
      <form className="mb-4 flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); setApplied(form); }}>
        <label className="flex flex-col text-sm">Event type
          <select className="rounded border p-1" value={form.type} onChange={set("type")}>
            <option value="">All</option>
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        {FIELDS.map(([k, label]) => (
          <label key={k} className="flex flex-col text-sm">{label}
            <input className="rounded border p-1" value={form[k]} onChange={set(k)} />
          </label>
        ))}
        <label className="flex flex-col text-sm">From
          <input type="datetime-local" className="rounded border p-1" value={form.date_from} onChange={set("date_from")} />
        </label>
        <label className="flex flex-col text-sm">To
          <input type="datetime-local" className="rounded border p-1" value={form.date_to} onChange={set("date_to")} />
        </label>
        <button className="rounded bg-slate-800 px-3 py-1 text-white">Search</button>
        <button type="button" className="text-sm underline" onClick={() => { setForm(EMPTY); setApplied(EMPTY); }}>Clear</button>
      </form>
      {results.isError && <p className="text-red-600">{results.error.message}</p>}
      {results.data && (
        <>
          <p className="mb-2 text-sm text-slate-600">
            Showing {results.data.items.length} of {results.data.total} events, newest first.
          </p>
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b">
              <th className="p-1">#</th><th className="p-1">Time (UTC)</th><th className="p-1">Type</th>
              <th className="p-1">Actor</th><th className="p-1">Parents</th><th className="p-1">Payload</th>
            </tr></thead>
            <tbody>
              {results.data.items.map((e) => (
                <tr key={e.id} className={`border-b align-top ${e.type === "access_denied" ? "bg-red-50" : ""}`}>
                  <td className="p-1">{e.id}</td>
                  <td className="p-1 whitespace-nowrap">{e.timestamp}</td>
                  <td className="p-1">{e.type}</td>
                  <td className="p-1">
                    {e.actor.name}
                    {e.actor.role && <span className="text-slate-500"> ({e.actor.role})</span>}
                    {e.actor.model && <span className="block text-slate-500">{e.actor.model} · prompt {e.actor.prompt_version}</span>}
                  </td>
                  <td className="p-1">{e.parent_ids.join(", ") || "—"}</td>
                  <td className="p-1"><code className="break-all text-xs">{JSON.stringify(e.payload)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
          {results.data.items.length === 0 && <p className="mt-2 text-slate-600">No events match.</p>}
        </>
      )}
    </div>
  );
}
