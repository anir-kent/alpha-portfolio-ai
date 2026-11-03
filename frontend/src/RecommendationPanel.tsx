import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api/client";
import type { components } from "./api/schema";

type Detail = components["schemas"]["PortfolioDetail"];
type Rec = components["schemas"]["RecommendationOut"];
type Rule = components["schemas"]["RuleOut"];
type LineIn = components["schemas"]["TradeLineIn"];
type Action = "accept" | "reject" | "modify";

const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const BADGE = {
  pass: "bg-slate-100 text-slate-700",
  warning: "bg-amber-100 font-semibold text-amber-800",
  breach: "bg-red-100 font-semibold text-red-800",
};
const STATUS_LABEL: Record<Rec["status"], string> = {
  pending_advisor: "Pending Advisor decision",
  pending_compliance: "Pending Compliance (rule breach)",
  approved: "Approved: cleared to act outside this system",
  rejected: "Rejected",
  superseded: "Superseded",
};

function Lines({ rec }: { rec: Rec }) {
  return (
    <table className="w-full text-left text-sm">
      <thead><tr className="border-b text-slate-500"><th className="p-1">Side</th><th>Instrument</th><th>Account</th><th>Qty</th><th>Amount</th><th>% of Portfolio</th></tr></thead>
      <tbody>
        {rec.trade_lines.map((l) => (
          <tr key={`${l.account_id}-${l.symbol}`} className="border-b">
            <td className={`p-1 font-medium ${l.side === "sell" ? "text-red-700" : "text-green-700"}`}>{l.side}</td>
            <td>{l.symbol} <span className="text-slate-500">{l.name}</span></td><td>{l.account_id}</td>
            <td>{l.quantity}</td><td>{money(l.amount)}</td><td>{l.pct_of_portfolio.toFixed(2)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PostTradeRules({ rec }: { rec: Rec }) {
  const shown = rec.suitability.rules.filter((r) => r.status !== "pass");
  return (
    <div>
      <p className="text-sm text-slate-500">
        Post-trade suitability <span className={`rounded px-1.5 py-0.5 ${BADGE[rec.suitability.status]}`}>{rec.suitability.status}</span>
      </p>
      {shown.length === 0 ? <p className="text-sm text-slate-600">All seven Suitability Rules pass after these Trade Lines.</p> : (
        <ul className="mt-1 space-y-1 text-sm">
          {shown.map((r) => (
            <li key={r.rule_id} className="rounded border p-2">
              <span className="font-mono text-xs text-slate-500">{r.rule_id}</span> <span className="font-medium">{r.name}</span>{" "}
              <span className={`rounded px-1.5 py-0.5 text-xs ${BADGE[r.status]}`}>{r.status}</span>
              <p className="text-slate-600">{r.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ModifyEditor({ rec, accounts, onChange }: { rec: Rec; accounts: string[]; onChange: (l: LineIn[]) => void }) {
  const [lines, setLines] = useState<LineIn[]>(rec.trade_lines.map(({ account_id, symbol, side, quantity }) => ({ account_id, symbol, side, quantity })));
  const update = (next: LineIn[]) => { setLines(next); onChange(next); };
  const patch = (i: number, p: Partial<LineIn>) => update(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-600">Edit the full set of Trade Lines. The Suitability Rules re-run as soon as you submit.</p>
      {lines.map((l, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 text-sm">
          <select aria-label="Side" className="rounded border p-1" value={l.side} onChange={(e) => patch(i, { side: e.target.value as LineIn["side"] })}>
            <option value="buy">buy</option><option value="sell">sell</option>
          </select>
          <input aria-label="Symbol" className="w-24 rounded border p-1" value={l.symbol} onChange={(e) => patch(i, { symbol: e.target.value.toUpperCase() })} />
          <select aria-label="Account" className="rounded border p-1" value={l.account_id} onChange={(e) => patch(i, { account_id: e.target.value })}>
            {accounts.map((a) => <option key={a}>{a}</option>)}
          </select>
          <input aria-label="Quantity" type="number" min={1} className="w-28 rounded border p-1" value={l.quantity} onChange={(e) => patch(i, { quantity: Math.trunc(Number(e.target.value)) })} />
          <button type="button" className="text-slate-500 underline" onClick={() => update(lines.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button type="button" className="text-sm underline" onClick={() => update([...lines, { account_id: accounts[0], symbol: "", side: "buy", quantity: 1 }])}>Add Trade Line</button>
    </div>
  );
}

function DecisionForm({ rec, accounts, portfolioId }: { rec: Rec; accounts: string[]; portfolioId: string }) {
  const qc = useQueryClient();
  const [action, setAction] = useState<Action>("accept");
  const [rationale, setRationale] = useState("");
  const [lines, setLines] = useState<LineIn[]>([]);
  const [newBreaches, setNewBreaches] = useState<Rule[]>([]);
  const decide = useMutation({
    mutationFn: async () => {
      const body = { action, rationale: rationale.trim() || null, trade_lines: action === "modify" ? lines : null };
      const { data, error } = await api.POST("/api/recommendations/{recommendation_id}/decision", { params: { path: { recommendation_id: rec.id } }, body });
      if (!data) {
        const detail = (error as { detail?: unknown } | undefined)?.detail;
        throw new Error(typeof detail === "string" ? detail : "Could not record the Decision");
      }
      return data;
    },
    onSuccess: (r) => {
      setNewBreaches(r.new_breaches);
      setRationale("");
      qc.invalidateQueries({ queryKey: ["portfolio", portfolioId] });
    },
  });
  const needsWhy = action !== "accept";
  return (
    <form className="space-y-3 rounded border p-3" onSubmit={(e) => { e.preventDefault(); decide.mutate(); }} aria-label="Decision">
      <fieldset className="flex gap-4 text-sm">
        <legend className="sr-only">Decision</legend>
        {(["accept", "modify", "reject"] as const).map((a) => (
          <label key={a}><input type="radio" name="action" checked={action === a} onChange={() => setAction(a)} /> <span className="capitalize">{a}</span></label>
        ))}
      </fieldset>
      {action === "modify" && <ModifyEditor rec={rec} accounts={accounts} onChange={setLines} />}
      <label className="block text-sm">
        Rationale {needsWhy ? <span className="text-red-700">(required)</span> : <span className="text-slate-500">(optional)</span>}
        <textarea className="mt-1 w-full rounded border p-2" rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} />
      </label>
      <button className="rounded bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-50" disabled={decide.isPending || (needsWhy && !rationale.trim())}>
        Record Decision
      </button>
      {decide.isError && <p role="alert" className="text-sm text-red-600">{decide.error.message}</p>}
      {newBreaches.length > 0 && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          <p className="font-semibold">The modified version breaches {newBreaches.length === 1 ? "a Suitability Rule" : "Suitability Rules"} the earlier version did not:</p>
          <ul className="list-disc pl-5">{newBreaches.map((r) => <li key={r.rule_id}>{r.rule_id} {r.name}: {r.message}</li>)}</ul>
        </div>
      )}
    </form>
  );
}

export function RecommendationPanel({ p, canDecide }: { p: Detail; canDecide: boolean }) {
  const rec = p.recommendation;
  const accounts = [...new Set(p.holdings.map((h) => h.account_id))].sort();
  return (
    <div className="space-y-4">
      <p className="rounded border border-sky-200 bg-sky-50 p-2 text-sm text-sky-900">
        Nothing is executed from this system. Approved means the Recommendation is cleared to act on outside this system.
      </p>
      {!rec ? <p className="text-slate-600">{p.drift ? "No Recommendation: every Asset Class is within its Tolerance Band." : "No analysis run yet; run an analysis from the queue."}</p> : (
        <>
          <div>
            <p className="text-sm">
              <span className="font-semibold">Version {rec.version}</span> · <span aria-label="Recommendation status">{STATUS_LABEL[rec.status]}</span> ·
              turnover {rec.turnover_pct.toFixed(1)}% of {money(rec.total_value)} · by {rec.created_by}
            </p>
            <p className="text-sm text-slate-600">{rec.summary}</p>
          </div>
          <Lines rec={rec} />
          <PostTradeRules rec={rec} />
          {rec.status === "pending_advisor" && canDecide && <DecisionForm key={rec.id} rec={rec} accounts={accounts} portfolioId={p.portfolio_id} />}
        </>
      )}
      <div>
        <h3 className="mb-1 text-sm font-semibold">Version history</h3>
        {p.history.versions.length === 0 ? <p className="text-sm text-slate-600">No Recommendations yet.</p> : (
          <ol className="space-y-1 text-sm">
            {p.history.versions.map((v) => (
              <li key={v.id}>
                v{v.version} · {STATUS_LABEL[v.status]} · {v.created_at.slice(0, 16).replace("T", " ")} · by {v.created_by}
                {v.parent_id && <span className="text-slate-500"> · modified from #{v.parent_id}</span>}
                {" "}<span className={`rounded px-1.5 py-0.5 text-xs ${BADGE[v.suitability_status]}`}>{v.suitability_status}</span>
                <ul className="ml-4 list-disc text-slate-600">
                  {p.history.decisions.filter((d) => d.recommendation_id === v.id).map((d) => (
                    <li key={d.id}>{d.action} by {d.actor_name} ({d.actor_role}){d.rationale ? `: ${d.rationale}` : ""}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
