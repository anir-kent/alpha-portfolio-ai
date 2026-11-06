import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "./api/client";
import { RecommendationPanel } from "./RecommendationPanel";
import type { components } from "./api/schema";
import { DeltaBar, DRIFT_TONE, Empty, ErrorLine, Icon, PageHeader, Panel, Pill, RULE_TONE, money, pct, pp } from "./ui";

type Detail = components["schemas"]["PortfolioDetail"];
type Suitability = NonNullable<Detail["suitability"]>;
const BAR = {
  ok: "linear-gradient(to bottom, #5fd1a0, #0b7a4b)",
  warn: "linear-gradient(to bottom, #f1c05a, #b7791f)",
  breach: "linear-gradient(to bottom, #ef7a70, #b3261e)",
} as const;

function Masked({ value }: { value: string | null | undefined }) {
  return value != null ? (
    <>{value}</>
  ) : (
    <Pill tone="mute" title="Sensitive client field, masked for your role">
      <Icon name="lock" size={11} />
      Masked
    </Pill>
  );
}

function SuitabilityPanel({ suitability }: { suitability: Suitability }) {
  return (
    <Panel
      title="Suitability"
      label="Suitability"
      aside={
        <>
          <Pill tone={RULE_TONE[suitability.status]}>{suitability.status}</Pill>
          <span className="mono">run #{suitability.run_id}</span>
        </>
      }
      flush
    >
      <ul className="divide-y divide-line">
        {suitability.rules.map((r) => (
          <li key={r.rule_id} className="px-3 py-1.5">
            <div className="flex items-center gap-2">
              <span className="mono w-9 text-ink-3">{r.rule_id}</span>
              <span className="font-medium">{r.name}</span>
              <span className="ml-auto">
                <Pill tone={RULE_TONE[r.status]}>{r.status}</Pill>
              </span>
            </div>
            <p className="pl-11 text-ink-2">{r.message}</p>
            {r.findings.length > 0 && (
              <ul className="pl-11 text-[0.8461rem] text-ink-3">
                {r.findings.map((f) => (
                  <li key={f.subject}>
                    <span className="mono">
                      {f.subject}: {f.actual}% vs limit {f.limit}% ({f.status})
                    </span>
                    {f.note ? ` · ${f.note}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Actual bar over a shaded Tolerance Band: green = within warn, amber = warn..breach, outside = breach. Target is the tick. */
function AllocationChart({ drift }: { drift: NonNullable<Detail["drift"]> }) {
  const { warn, breach } = drift.tolerance_band;
  const axis = Math.min(
    100,
    Math.max(...drift.asset_classes.flatMap((a) => [a.actual_pct, a.target_pct + breach])) * 1.05,
  );
  const x = (v: number) => `${Math.max(0, Math.min(100, (v / axis) * 100))}%`;
  return (
    <Panel
      title="Allocation vs target"
      label="Allocation vs target"
      aside={
        <>
          Portfolio Drift <strong className="mono text-ink">{drift.portfolio_drift_pp.toFixed(1)} pp</strong> · band
          warn {warn} / breach {breach} pp · run #{drift.run_id}
        </>
      }
    >
      <ul className="space-y-2.5">
        {drift.asset_classes.map((a) => (
          <li
            key={a.asset_class}
            aria-label={`${a.asset_class} actual ${a.actual_pct.toFixed(1)}% target ${a.target_pct.toFixed(1)}%`}
          >
            <div className="mb-0.5 flex items-baseline gap-2">
              <span className="w-24 font-medium capitalize">{a.asset_class}</span>
              <span className="mono text-ink-2">
                {pct(a.actual_pct)} <span className="text-ink-3">vs target</span> {pct(a.target_pct)}
              </span>
              <span className="ml-auto flex items-center gap-2">
                <DeltaBar
                  value={a.signed_pp}
                  max={Math.max(breach * 2, Math.abs(a.signed_pp))}
                  tone={DRIFT_TONE[a.status]}
                  width="8rem"
                />
                <span className="mono w-16 text-right">{pp(a.signed_pp)}</span>
                <Pill tone={DRIFT_TONE[a.status]}>{a.status}</Pill>
              </span>
            </div>
            <div className="gridtex relative h-5 rounded-full">
              <div
                className="absolute inset-y-0 bg-warn-bg"
                style={{
                  left: x(a.target_pct - breach),
                  width: `calc(${x(a.target_pct + breach)} - ${x(a.target_pct - breach)})`,
                }}
                title={`Breach band ±${breach} pp`}
              />
              <div
                className="absolute inset-y-0 bg-pos-bg"
                style={{
                  left: x(a.target_pct - warn),
                  width: `calc(${x(a.target_pct + warn)} - ${x(a.target_pct - warn)})`,
                }}
                title={`Within tolerance ±${warn} pp`}
              />
              <div
                className="rod absolute inset-y-1"
                style={{
                  left: 0,
                  width: x(a.actual_pct),
                  background: BAR[a.status],
                  transition: "width 240ms ease-out",
                }}
              />
              <div
                className="absolute -inset-y-1 w-0.5 rounded-full bg-ink shadow-[0_0_0_1px_rgba(255,255,255,0.8)]"
                style={{ left: x(a.target_pct) }}
                title={`Target ${a.target_pct.toFixed(1)}%`}
              />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-2 flex gap-3 text-[0.7692rem] text-ink-3">
        <span>
          <i className="mr-1 inline-block size-2 rounded-full bg-pos-bg ring-1 ring-line-strong" />
          within ±{warn} pp
        </span>
        <span>
          <i className="mr-1 inline-block size-2 rounded-full bg-warn-bg ring-1 ring-line-strong" />
          warn to breach (±{breach} pp)
        </span>
        <span>
          <i className="mr-1 inline-block h-2.5 w-0.5 bg-ink align-middle" />
          target
        </span>
      </p>
    </Panel>
  );
}

function LookThrough({ rows }: { rows: Detail["sector_exposure"] }) {
  const max = Math.max(...rows.map((s) => s.weight_pct), 1);
  return (
    <Panel
      title="Sector exposure (look-through)"
      label="Sector exposure"
      aside={
        <span className="flex items-center gap-2">
          <i className="inline-block size-2 bg-brand" />
          direct
          <i className="inline-block size-2 bg-ai" />
          via funds
        </span>
      }
      flush
    >
      <table className="grid-table">
        <thead>
          <tr>
            <th>Sector</th>
            <th className="w-2/5">Direct + via funds</th>
            <th className="num">Total</th>
            <th className="num">Direct</th>
            <th className="num">Via funds</th>
          </tr>
        </thead>
        <tbody>
          {[...rows]
            .sort((a, b) => b.weight_pct - a.weight_pct)
            .map((s) => (
              <tr key={s.sector}>
                <td>{s.sector}</td>
                <td>
                  <div
                    className="flex h-2 overflow-hidden rounded-full bg-sunken"
                    style={{ width: `${(s.weight_pct / max) * 100}%` }}
                  >
                    <div className="bg-brand" style={{ width: `${(s.direct_pct / s.weight_pct) * 100}%` }} />
                    <div className="bg-ai" style={{ width: `${(s.via_funds_pct / s.weight_pct) * 100}%` }} />
                  </div>
                </td>
                <td className="num font-semibold">{s.weight_pct.toFixed(1)}%</td>
                <td className="num">{s.direct_pct.toFixed(1)}%</td>
                <td className="num">
                  {s.via_funds_pct > 0 ? (
                    <span className="font-semibold text-ai">{s.via_funds_pct.toFixed(1)}%</span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </Panel>
  );
}

export function PortfolioPage({ canDecide = false }: { canDecide?: boolean }) {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["portfolio", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/portfolios/{portfolio_id}", {
        params: { path: { portfolio_id: id! } },
      });
      if (error || !data) throw new Error("Could not load the Portfolio");
      return data;
    },
  });
  if (q.isError) return <ErrorLine>{q.error.message}</ErrorLine>;
  if (!q.data) return <Empty>Loading…</Empty>;
  const p = q.data;
  const c = p.client;
  const masked = c.name == null || c.email == null;
  return (
    <section aria-label="Portfolio" className="space-y-3">
      <PageHeader
        title={
          <>
            {c.name ?? "Name hidden"} <span className="mono font-normal text-ink-3">{c.id}</span>
          </>
        }
        sub={
          <>
            <Link to="/queue" className="text-brand hover:underline">
              ← Queue
            </Link>{" "}
            · <span className="mono">{money(p.total_value)}</span> as of <span className="mono">{p.as_of}</span>
          </>
        }
        actions={
          masked ? (
            <Pill tone="warn" title="Name and contact fields are masked for relationship managers">
              <Icon name="lock" size={11} />
              PII masked for your role
            </Pill>
          ) : (
            <Pill tone="pos">Full client detail</Pill>
          )
        }
      />
      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="min-w-0 space-y-3">
          {p.drift ? (
            <AllocationChart drift={p.drift} />
          ) : (
            <Panel title="Allocation vs target">
              <Empty>No analysis run yet; run an analysis from the queue.</Empty>
            </Panel>
          )}
          <Panel title="Recommendation" label="Recommendation">
            <RecommendationPanel p={p} canDecide={canDecide} />
          </Panel>
          <LookThrough rows={p.sector_exposure} />
          <Panel title={`Holdings (${p.holdings.length})`} flush>
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Name</th>
                  <th>Asset Class</th>
                  <th>Account</th>
                  <th className="num">Qty</th>
                  <th className="num">Price</th>
                  <th className="num">Value</th>
                  <th className="num">Weight</th>
                </tr>
              </thead>
              <tbody>
                {p.holdings.map((h) => (
                  <tr key={`${h.account_id}-${h.symbol}`}>
                    <td className="mono font-semibold">{h.symbol}</td>
                    <td>{h.name}</td>
                    <td className="capitalize">{h.asset_class}</td>
                    <td className="mono">{h.account_id}</td>
                    <td className="num">{h.quantity}</td>
                    <td className="num">{h.price.toFixed(2)}</td>
                    <td className="num">{money(h.market_value)}</td>
                    <td className="num">{h.weight_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
        <aside className="min-w-0 space-y-3">
          <Panel title="Client" label="Client">
            <dl className="grid grid-cols-[7.5rem_1fr] gap-y-1">
              <dt className="text-ink-3">Email</dt>
              <dd>
                <Masked value={c.email} />
              </dd>
              <dt className="text-ink-3">Risk Profile</dt>
              <dd className="capitalize">{c.risk_profile}</dd>
              <dt className="text-ink-3">Objective</dt>
              <dd>{c.objective}</dd>
              <dt className="text-ink-3">Horizon</dt>
              <dd className="mono">{c.horizon_years} years</dd>
              <dt className="text-ink-3">Liquidity needs</dt>
              <dd className="mono">{c.liquidity_needs_pct}%</dd>
              <dt className="text-ink-3">Review due</dt>
              <dd className="mono">{c.review_due}</dd>
              <dt className="text-ink-3">Restrictions</dt>
              <dd className="flex flex-wrap gap-1">
                {p.restrictions.length
                  ? p.restrictions.map((r) => (
                      <Pill key={`${r.kind}-${r.value}`} tone="neg">
                        {r.kind}: {r.value}
                      </Pill>
                    ))
                  : "None"}
              </dd>
            </dl>
          </Panel>
          {p.suitability ? (
            <SuitabilityPanel suitability={p.suitability} />
          ) : (
            <Panel title="Suitability">
              <Empty>No analysis run yet; run an analysis from the queue.</Empty>
            </Panel>
          )}
        </aside>
      </div>
    </section>
  );
}
