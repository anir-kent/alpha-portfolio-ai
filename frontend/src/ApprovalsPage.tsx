import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";

type Item = components["schemas"]["ApprovalItem"];

const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const BADGE = { warning: "bg-amber-100 font-semibold text-amber-800", breach: "bg-red-100 font-semibold text-red-800" } as Record<string, string>;
const TITLE = { compliance: "Pending Compliance", committee: "Pending Investment Committee" } as Record<string, string>;
const ACTIONS = {
  compliance: [{ action: "approve", label: "Approve exception" }, { action: "block", label: "Block" }],
  committee: [{ action: "approve", label: "Approve" }, { action: "reject", label: "Reject" }],
} as Record<string, { action: string; label: string }[]>;

function StepForm({ item, canCompliance, canCommittee }: { item: Item; canCompliance: boolean; canCommittee: boolean }) {
  const qc = useQueryClient();
  const [rationale, setRationale] = useState("");
  const allowed = item.step === "compliance" ? canCompliance : canCommittee;
  const decide = useMutation({
    mutationFn: async (action: string) => {
      const path = { params: { path: { recommendation_id: item.recommendation.id } } };
      const { data, error } = item.step === "compliance"
        ? await api.POST("/api/recommendations/{recommendation_id}/compliance", { ...path, body: { action: action as "approve" | "block", rationale } })
        : await api.POST("/api/recommendations/{recommendation_id}/committee", { ...path, body: { action: action as "approve" | "reject", rationale } });
      if (!data) {
        const detail = (error as { detail?: unknown } | undefined)?.detail;
        throw new Error(typeof detail === "string" ? detail : "Could not record the Decision");
      }
    },
    onSuccess: () => { setRationale(""); qc.invalidateQueries({ queryKey: ["approvals"] }); },
  });
  if (!allowed) return null;
  return (
    <form className="space-y-2" aria-label={`${item.step} decision`} onSubmit={(e) => e.preventDefault()}>
      <label className="block text-sm">
        Rationale <span className="text-red-700">(required)</span>
        <textarea className="mt-1 w-full rounded border p-2" rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} />
      </label>
      <div className="flex gap-2">
        {ACTIONS[item.step].map((a) => (
          <button key={a.action} type="button" className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={decide.isPending || !rationale.trim()} onClick={() => decide.mutate(a.action)}>{a.label}</button>
        ))}
      </div>
      {decide.isError && <p role="alert" className="text-sm text-red-600">{decide.error.message}</p>}
    </form>
  );
}

function ItemCard({ item, canCompliance, canCommittee }: { item: Item; canCompliance: boolean; canCommittee: boolean }) {
  const r = item.recommendation;
  return (
    <li className="space-y-3 rounded border p-3">
      <p className="text-sm">
        <Link className="font-medium underline" to={`/portfolios/${item.portfolio_id}`}>{item.portfolio_id}</Link>
        {item.client_name && <> · {item.client_name}</>} · {item.risk_profile} · version {r.version} · turnover {r.turnover_pct.toFixed(1)}% of {money(r.total_value)}
      </p>
      <p className="text-sm text-slate-600">{r.summary}</p>
      <p className="text-xs text-slate-500">Required steps: {r.approval.required_steps.join(" → ")}</p>
      {r.approval.reasons.length > 0 && (
        <div className="rounded border border-violet-200 bg-violet-50 p-2 text-sm text-violet-900">
          <p className="font-semibold">High-impact (thresholds: turnover {r.approval.thresholds.turnover_pct}%, single Trade Line {r.approval.thresholds.trade_line_pct}%)</p>
          <ul className="list-disc pl-5">{r.approval.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      <table className="w-full text-left text-sm">
        <thead><tr className="border-b text-slate-500"><th className="p-1">Side</th><th>Instrument</th><th>Account</th><th>Qty</th><th>Amount</th><th>% of Portfolio</th></tr></thead>
        <tbody>
          {r.trade_lines.map((l) => (
            <tr key={`${l.account_id}-${l.symbol}`} className="border-b">
              <td className="p-1">{l.side}</td><td>{l.symbol}</td><td>{l.account_id}</td><td>{l.quantity}</td><td>{money(l.amount)}</td><td>{l.pct_of_portfolio.toFixed(2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <h3 className="text-sm font-semibold">Suitability flags</h3>
        {item.rules.length === 0 ? <p className="text-sm text-slate-600">No warnings or breaches.</p> : (
          <ul className="space-y-1 text-sm">
            {item.rules.map((rule) => (
              <li key={rule.rule_id} className="rounded border p-2">
                <span className="font-mono text-xs text-slate-500">{rule.rule_id}</span> <span className="font-medium">{rule.name}</span>{" "}
                <span className={`rounded px-1.5 py-0.5 text-xs ${BADGE[rule.status]}`}>{rule.status}</span>
                <p className="text-slate-600">{rule.message}</p>
                <ul className="ml-4 list-disc">
                  {rule.findings.map((f) => (
                    <li key={f.subject}>
                      {f.subject}: limit {f.limit}%, actual {f.actual}% {f.note && <span className="text-slate-500">({f.note})</span>}
                      {f.affected_trade_lines.length > 0 && (
                        <span className="text-slate-600"> · affected Trade Lines: {f.affected_trade_lines.map((l) => `${l.side} ${l.symbol} ${l.pct_of_portfolio.toFixed(1)}%`).join(", ")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold">Client Restrictions</h3>
        {item.restrictions.length === 0 ? <p className="text-sm text-slate-600">None.</p> : (
          <ul className="list-disc pl-5 text-sm">{item.restrictions.map((x) => <li key={`${x.kind}-${x.value}`}>{x.kind}: {x.value}</li>)}</ul>
        )}
      </div>
      <StepForm item={item} canCompliance={canCompliance} canCommittee={canCommittee} />
    </li>
  );
}

/** The shared pending-approvals panel: the server returns only what the caller's role may act on. */
export function ApprovalsPage({ permissions }: { permissions: string[] }) {
  const q = useQuery({
    queryKey: ["approvals"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/approvals");
      if (error || !data) throw new Error("Could not load pending approvals");
      return data;
    },
  });
  const canCompliance = permissions.includes("compliance:decide");
  const canCommittee = permissions.includes("committee:decide");
  const steps = (["compliance", "committee"] as const).filter((s) => (s === "compliance" ? canCompliance : canCommittee));
  if (q.isError) return <p role="alert" className="text-red-600">{q.error.message}</p>;
  const items = q.data?.items ?? [];
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Pending approvals</h1>
      {steps.map((s) => {
        const mine = items.filter((i) => i.step === s);
        return (
          <section key={s} className="space-y-2">
            <h2 className="font-semibold">{TITLE[s]} ({mine.length})</h2>
            {mine.length === 0 ? <p className="text-sm text-slate-600">Nothing is waiting.</p> : (
              <ul className="space-y-3">{mine.map((i) => <ItemCard key={i.recommendation.id} item={i} canCompliance={canCompliance} canCommittee={canCommittee} />)}</ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
