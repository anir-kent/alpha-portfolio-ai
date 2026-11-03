import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";

type Detail = components["schemas"]["PortfolioDetail"];
const STATUS_STYLE = { ok: "text-slate-600", warn: "font-semibold text-amber-700", breach: "font-semibold text-red-700" };
const STATUS_BAR = { ok: "bg-sky-600", warn: "bg-amber-500", breach: "bg-red-600" };
const money = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const signed = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(1)}`;

function AllocationChart({ drift }: { drift: NonNullable<Detail["drift"]> }) {
  return (
    <div>
      <p className="mb-2 text-sm text-slate-500">
        Portfolio Drift <strong>{drift.portfolio_drift_pp.toFixed(1)} pp</strong> · Tolerance Band warn {drift.tolerance_band.warn} pp / breach {drift.tolerance_band.breach} pp · run #{drift.run_id}
      </p>
      <ul className="space-y-3">
        {drift.asset_classes.map((a) => (
          <li key={a.asset_class} aria-label={`${a.asset_class} actual ${a.actual_pct.toFixed(1)}% target ${a.target_pct.toFixed(1)}%`}>
            <div className="flex justify-between text-sm">
              <span className="capitalize">{a.asset_class}</span>
              <span className={STATUS_STYLE[a.status]}>
                {a.actual_pct.toFixed(1)}% vs target {a.target_pct.toFixed(1)}% ({signed(a.signed_pp)} pp, {a.status})
              </span>
            </div>
            <div className="relative h-4 rounded bg-slate-100">
              <div className={`h-4 rounded ${STATUS_BAR[a.status]}`} style={{ width: `${Math.min(a.actual_pct, 100)}%` }} />
              <div className="absolute top-0 h-4 w-0.5 bg-slate-900" style={{ left: `${a.target_pct}%` }} title={`Target ${a.target_pct.toFixed(1)}%`} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PortfolioPage() {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["portfolio", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/portfolios/{portfolio_id}", { params: { path: { portfolio_id: id! } } });
      if (error || !data) throw new Error("Could not load the Portfolio");
      return data;
    },
  });
  if (q.isError) return <p role="alert" className="text-red-600">{q.error.message}</p>;
  if (!q.data) return <p className="text-slate-500">Loading…</p>;
  const p = q.data;
  const c = p.client;
  return (
    <section aria-label="Portfolio" className="space-y-6">
      <header>
        <Link to="/queue" className="text-sm text-slate-500 underline">← Queue</Link>
        <h1 className="text-xl font-semibold">{c.name ?? "Name hidden"} <span className="text-slate-500">{c.id}</span></h1>
        <p className="text-sm text-slate-500">{money(p.total_value)} as of {p.as_of}</p>
      </header>

      <div>
        <h2 className="mb-2 font-semibold">Client</h2>
        <dl className="grid max-w-xl grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-slate-500">Email</dt><dd>{c.email ?? "Hidden"}</dd>
          <dt className="text-slate-500">Risk Profile</dt><dd>{c.risk_profile}</dd>
          <dt className="text-slate-500">Objective</dt><dd>{c.objective}</dd>
          <dt className="text-slate-500">Horizon</dt><dd>{c.horizon_years} years</dd>
          <dt className="text-slate-500">Liquidity needs</dt><dd>{c.liquidity_needs_pct}%</dd>
          <dt className="text-slate-500">Review due</dt><dd>{c.review_due}</dd>
          <dt className="text-slate-500">Restrictions</dt>
          <dd>{p.restrictions.length ? p.restrictions.map((r) => `${r.kind}: ${r.value}`).join(", ") : "None"}</dd>
        </dl>
      </div>

      <div>
        <h2 className="mb-2 font-semibold">Allocation vs target</h2>
        {p.drift ? <AllocationChart drift={p.drift} /> : <p className="text-slate-600">No analysis run yet; run an analysis from the queue.</p>}
      </div>

      <div>
        <h2 className="mb-2 font-semibold">Sector exposure (look-through)</h2>
        <table className="w-full max-w-xl text-left text-sm">
          <thead><tr className="border-b text-slate-500"><th className="p-1">Sector</th><th>Total</th><th>Direct</th><th>Via funds</th></tr></thead>
          <tbody>
            {p.sector_exposure.map((s) => (
              <tr key={s.sector} className="border-b">
                <td className="p-1">{s.sector}</td>
                <td>{s.weight_pct.toFixed(1)}%</td><td>{s.direct_pct.toFixed(1)}%</td><td>{s.via_funds_pct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="mb-2 font-semibold">Holdings</h2>
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b text-slate-500">
            <th className="p-1">Symbol</th><th>Name</th><th>Asset Class</th><th>Account</th><th>Qty</th><th>Price</th><th>Value</th><th>Weight</th>
          </tr></thead>
          <tbody>
            {p.holdings.map((h) => (
              <tr key={`${h.account_id}-${h.symbol}`} className="border-b">
                <td className="p-1">{h.symbol}</td><td>{h.name}</td><td>{h.asset_class}</td><td>{h.account_id}</td>
                <td>{h.quantity}</td><td>{h.price.toFixed(2)}</td><td>{money(h.market_value)}</td><td>{h.weight_pct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="mb-2 font-semibold">Version and Decision history</h2>
        {p.history.versions.length + p.history.decisions.length === 0
          ? <p className="text-slate-600">No Recommendations or Decisions yet.</p>
          : <pre className="text-xs">{JSON.stringify(p.history, null, 2)}</pre>}
      </div>
    </section>
  );
}
