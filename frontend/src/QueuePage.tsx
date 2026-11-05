import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import { Citations, DeltaBar, DRIFT_TONE, Empty, ErrorLine, HoverPeek, Icon, LABEL_TONE, PageHeader, Panel, Pill, ScoreDial, pp, useQueue, type QueueParams } from "./ui";

const COMPONENT_COLOR = { drift: "#2253d4", risk: "#475569", opportunity: "#0f766e", urgency: "#b7791f" } as const;
const COMPONENT_NAME = { drift: "Drift", risk: "Risk", opportunity: "Opp", urgency: "Urgency" } as const;
const LABELS = ["High", "Medium", "Low"] as const;

type Item = NonNullable<ReturnType<typeof useQueue>["data"]>["items"][number];

/** Four mini-bars, each scaled to its own weight (drift 40 / risk 30 / opportunity 20 / urgency 10). */
function ScoreBreakdown({ components }: { components: Item["components"] }) {
  return (
    <div className="grid w-52 grid-cols-4 gap-1.5" role="img" aria-label={components.map((c) => `${c.name} ${c.points.toFixed(1)}`).join(", ")}>
      {components.map((c) => {
        const max = c.weight * 100;
        return (
          <div key={c.name} title={`${c.name}: ${c.points.toFixed(1)} of ${max.toFixed(0)} (raw ${c.raw.toFixed(0)} × ${c.weight})`}>
            <div className="gridtex h-2 overflow-hidden rounded-full p-px">
              <div className="rod h-full" style={{ width: `${Math.max(6, Math.min(100, (c.points / max) * 100))}%`, background: `linear-gradient(to bottom, color-mix(in srgb, ${COMPONENT_COLOR[c.name]} 70%, white), ${COMPONENT_COLOR[c.name]})` }} />
            </div>
            <p className="mt-0.5 text-[0.7692rem] leading-tight text-ink-3">{COMPONENT_NAME[c.name]} <span className="mono text-ink-2">{c.points.toFixed(0)}</span><span className="text-ink-3">/{max.toFixed(0)}</span></p>
          </div>
        );
      })}
    </div>
  );
}

/** One line in the row; the full narrative (summary, grounded claims with citations, flagged claims) opens on hover or focus. */
function Narrative({ r }: { r: Item }) {
  const n = r.narrative;
  if (!n) return null;
  if (n.status === "failed") return <p className="mt-1 w-[28rem] text-ink-3">Narrative unavailable (AI step failed; scores are unaffected).</p>;
  const grounded = n.claims.filter((c) => c.grounded);
  const flagged = n.claims.filter((c) => !c.grounded);
  const line = n.summary || grounded[0]?.text;
  if (!line && flagged.length === 0) return null;
  return (
    <div className="mt-1 w-[28rem]">
      <HoverPeek
        label={`Narrative for ${r.client_name ?? r.client_id}: ${line ?? "flagged claims"}`}
        trigger={
          <div className="flex min-w-0 items-center gap-1.5 px-1 py-0.5">
            <Pill tone="ai"><Icon name="spark" size={10} />AI</Pill>
            <span className="min-w-0 flex-1 truncate text-ink-2">{line}</span>
            {flagged.length > 0 && <Pill tone="warn" title="AI claims flagged, not shown as fact"><Icon name="alert" size={10} />{flagged.length} flagged</Pill>}
          </div>
        }
      >
        <div className="space-y-2">
          {n.summary && <p className="text-ink">{n.summary}</p>}
          {grounded.length > 0 && (
            <div>
              <p className="eyebrow mb-1">Grounded claims</p>
              <ul className="space-y-1.5">
                {grounded.map((c) => (
                  <li key={c.index} className="flex flex-wrap items-start gap-x-1.5 gap-y-0.5 text-ink-2">
                    <Pill tone="pos"><Icon name="approvals" size={10} />grounded</Pill><span className="min-w-0 flex-1">{c.text}</span><Citations citations={c.citations} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {flagged.length > 0 && (
            <div className="callout callout-warn !block">
              <p className="font-semibold"><Icon name="alert" size={12} /> {flagged.length} AI claim{flagged.length > 1 ? "s" : ""} flagged, not shown as fact</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {flagged.map((c) => <li key={c.index}>{c.text} <em>({c.issues.map((i) => i.message).join("; ")})</em></li>)}
              </ul>
            </div>
          )}
        </div>
      </HoverPeek>
    </div>
  );
}

export function QueuePage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState<QueueParams>({ sort: "score" });
  const queue = useQueue(filters);
  const run = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/analysis/runs");
      if (error) throw new Error("Analysis run failed");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });
  const set = (patch: Partial<QueueParams>) => setFilters((f) => ({ ...f, ...patch }));
  const items = queue.data?.items ?? [];

  return (
    <section aria-label="Priority queue">
      <PageHeader
        title="Priority queue"
        sub={queue.data?.as_of ? <>Run <span className="mono">#{queue.data.run_id}</span>, as of <span className="mono">{queue.data.as_of}</span> · score = drift 40% + risk 30% + opportunity 20% + urgency 10%</> : "Score = drift 40% + risk 30% + opportunity 20% + urgency 10%"}
        actions={<button className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Running…" : "Run analysis"}</button>}
      />
      {run.isError && <ErrorLine>{run.error.message}</ErrorLine>}

      <div className="panel mb-3 flex flex-wrap items-end gap-x-4 gap-y-2 px-3 py-2" role="search" aria-label="Queue filters">
        <div className="label">Priority
          <div className="seg" role="group" aria-label="Priority label">
            <button type="button" aria-pressed={!filters.label} onClick={() => set({ label: undefined })}>All</button>
            {LABELS.map((l) => <button key={l} type="button" aria-pressed={filters.label === l} onClick={() => set({ label: l })}>{l}</button>)}
          </div>
        </div>
        <div className="label">SLA
          <div className="seg" role="group" aria-label="SLA">
            <button type="button" aria-pressed={!filters.sla_breached} onClick={() => set({ sla_breached: undefined })}>All</button>
            <button type="button" aria-pressed={!!filters.sla_breached} onClick={() => set({ sla_breached: true })}>SLA breached only</button>
          </div>
        </div>
        <label className="label">Risk Profile
          <select className="field" value={filters.risk_profile ?? ""} onChange={(e) => set({ risk_profile: e.target.value || undefined })}>
            <option value="">All</option><option>conservative</option><option>moderate</option><option>growth</option><option>aggressive</option>
          </select>
        </label>
        <label className="label">Review due from
          <input type="date" className="field" value={filters.review_due_from ?? ""} onChange={(e) => set({ review_due_from: e.target.value || undefined })} />
        </label>
        <label className="label">to
          <input type="date" className="field" value={filters.review_due_to ?? ""} onChange={(e) => set({ review_due_to: e.target.value || undefined })} />
        </label>
        <label className="label">Sort
          <select className="field" value={filters.sort} onChange={(e) => set({ sort: e.target.value as QueueParams["sort"], order: undefined })}>
            <option value="score">Priority score</option><option value="review_due">Review due</option>
            <option value="risk_profile">Risk Profile</option><option value="label">Label</option>
          </select>
        </label>
        <span className="ml-auto text-ink-3">{items.length} portfolio{items.length === 1 ? "" : "s"}</span>
      </div>

      {queue.isError && <ErrorLine>{queue.error.message}</ErrorLine>}
      {queue.data && items.length === 0 && <Empty>No results. Run an analysis to score the Portfolios.</Empty>}
      {items.length > 0 && (
        <Panel flush>
          <table className="grid-table">
            <thead><tr>
              <th>Client</th><th>Risk Profile</th><th className="num">Priority</th><th>Why (drift / risk / opportunity / urgency)</th>
              <th className="num">Portfolio Drift</th><th>Worst Asset Class</th><th>Review due</th>
            </tr></thead>
            <tbody>
              {items.map((r) => {
                const worst = [...r.asset_class_drift].sort((a, b) => b.drift_pp - a.drift_pp)[0];
                return (
                  <tr key={r.portfolio_id}>
                    <td className="whitespace-nowrap">
                      <Link className="font-semibold text-brand hover:underline" to={`/portfolios/${r.portfolio_id}`}>{r.client_name ?? "Hidden"}</Link>
                      <br /><span className="mono text-ink-3">{r.client_id}</span>
                    </td>
                    <td className="capitalize">{r.risk_profile}</td>
                    <td className="num"><div className="flex flex-col items-end gap-0.5"><ScoreDial value={r.score} tone={r.label === "High" ? "neg" : r.label === "Medium" ? "warn" : "pos"} label="Priority score" /><Pill tone={LABEL_TONE[r.label]}>{r.label}</Pill></div></td>
                    <td><ScoreBreakdown components={r.components} /><Narrative r={r} /></td>
                    <td className="num">{r.portfolio_drift_pp.toFixed(1)} pp</td>
                    <td className="whitespace-nowrap">{worst && <div className="space-y-1"><div><span className="capitalize">{worst.asset_class}</span> <span className="mono">{pp(worst.signed_pp)}</span> <Pill tone={DRIFT_TONE[worst.status]}>{worst.status}</Pill></div><DeltaBar value={worst.signed_pp} max={Math.max(10, Math.abs(worst.signed_pp))} tone={DRIFT_TONE[worst.status]} width="9rem" /></div>}</td>
                    <td className="whitespace-nowrap"><span className="mono">{r.review_due}</span>{r.sla_breached && <> <Pill tone="neg">SLA breached</Pill></>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
      )}
    </section>
  );
}
