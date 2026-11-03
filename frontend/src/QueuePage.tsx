import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api/client";
import { Link } from "react-router-dom";
import type { operations } from "./api/schema";

type Params = NonNullable<operations["getQueue"]["parameters"]["query"]>;
const LABEL_STYLE = { High: "bg-red-100 text-red-800", Medium: "bg-amber-100 text-amber-800", Low: "bg-green-100 text-green-800" };
const COMPONENT_COLOR = { drift: "bg-sky-600", risk: "bg-rose-600", opportunity: "bg-violet-600", urgency: "bg-amber-600" };
const STATUS_STYLE = { ok: "text-slate-600", warn: "font-semibold text-amber-700", breach: "font-semibold text-red-700" };

export function QueuePage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState<Params>({ sort: "score" });
  const queue = useQuery({
    queryKey: ["queue", filters],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/queue", { params: { query: filters } });
      if (error || !data) throw new Error("Could not load the queue");
      return data;
    },
  });
  const run = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/analysis/runs");
      if (error) throw new Error("Analysis run failed");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
  const set = (patch: Partial<Params>) => setFilters((f) => ({ ...f, ...patch }));
  const items = queue.data?.items ?? [];

  return (
    <section aria-label="Priority queue">
      <header className="mb-4 flex items-center gap-4">
        <h1 className="text-xl font-semibold">Priority queue</h1>
        <button className="rounded bg-slate-800 px-3 py-1 text-white" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Running…" : "Run analysis"}
        </button>
        {queue.data?.as_of && <span className="text-sm text-slate-500">Run #{queue.data.run_id}, as of {queue.data.as_of}</span>}
      </header>
      {run.isError && <p role="alert" className="mb-2 text-red-600">{run.error.message}</p>}
      <div className="mb-4 flex flex-wrap gap-3 text-sm">
        <label>Label{" "}
          <select className="rounded border p-1" value={filters.label ?? ""} onChange={(e) => set({ label: (e.target.value || undefined) as Params["label"] })}>
            <option value="">All</option><option>High</option><option>Medium</option><option>Low</option>
          </select>
        </label>
        <label>Risk Profile{" "}
          <select className="rounded border p-1" value={filters.risk_profile ?? ""} onChange={(e) => set({ risk_profile: e.target.value || undefined })}>
            <option value="">All</option><option>conservative</option><option>moderate</option><option>growth</option><option>aggressive</option>
          </select>
        </label>
        <label>Review due from{" "}
          <input type="date" className="rounded border p-1" value={filters.review_due_from ?? ""} onChange={(e) => set({ review_due_from: e.target.value || undefined })} />
        </label>
        <label>to{" "}
          <input type="date" className="rounded border p-1" value={filters.review_due_to ?? ""} onChange={(e) => set({ review_due_to: e.target.value || undefined })} />
        </label>
        <label><input type="checkbox" checked={!!filters.sla_breached} onChange={(e) => set({ sla_breached: e.target.checked || undefined })} /> SLA breached only</label>
        <label>Sort{" "}
          <select className="rounded border p-1" value={filters.sort} onChange={(e) => set({ sort: e.target.value as Params["sort"], order: undefined })}>
            <option value="score">Priority score</option><option value="review_due">Review due</option>
            <option value="risk_profile">Risk Profile</option><option value="label">Label</option>
          </select>
        </label>
      </div>
      {queue.isError && <p role="alert" className="text-red-600">{queue.error.message}</p>}
      {queue.data && items.length === 0 && <p className="text-slate-600">No results. Run an analysis to score the Portfolios.</p>}
      {items.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b text-slate-500">
            <th className="p-2">Client</th><th>Risk Profile</th><th>Priority</th><th>Why (drift / risk / opportunity / urgency)</th>
            <th>Portfolio Drift</th><th>Worst Asset Class</th><th>Review due</th>
          </tr></thead>
          <tbody>
            {items.map((r) => {
              const worst = [...r.asset_class_drift].sort((a, b) => b.drift_pp - a.drift_pp)[0];
              return (
                <tr key={r.portfolio_id} className="border-b align-top">
                  <td className="p-2"><Link className="underline" to={`/portfolios/${r.portfolio_id}`}>{r.client_name ?? "Hidden"}</Link><br /><span className="text-slate-500">{r.client_id}</span></td>
                  <td>{r.risk_profile}</td>
                  <td><span className={`rounded px-2 py-0.5 ${LABEL_STYLE[r.label]}`}>{r.label}</span> <strong>{r.score.toFixed(1)}</strong></td>
                  <td>
                    <div className="flex h-3 w-48 overflow-hidden rounded bg-slate-100" role="img"
                      aria-label={r.components.map((c) => `${c.name} ${c.points.toFixed(1)}`).join(", ")}>
                      {r.components.map((c) => <div key={c.name} className={COMPONENT_COLOR[c.name]} style={{ width: `${c.points}%` }} title={`${c.name}: ${c.points.toFixed(1)} (raw ${c.raw.toFixed(0)} × ${c.weight})`} />)}
                    </div>
                    <span className="text-xs text-slate-500">{r.components.map((c) => `${c.name} ${c.points.toFixed(1)}`).join(" · ")}</span>
                  </td>
                  <td>{r.portfolio_drift_pp.toFixed(1)} pp</td>
                  <td className={STATUS_STYLE[worst.status]}>{worst.asset_class} {worst.signed_pp > 0 ? "+" : ""}{worst.signed_pp.toFixed(1)} pp ({worst.status})</td>
                  <td>{r.review_due}{r.sla_breached && <span className="ml-2 rounded bg-red-600 px-1.5 py-0.5 text-xs text-white">SLA breached</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
