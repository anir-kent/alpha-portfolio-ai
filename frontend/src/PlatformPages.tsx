import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "./api/client";
import { usePublishScreen } from "./assistantScreen";
import { Empty, ErrorLine, PageHeader, Panel, Pill, pct } from "./ui";

/** Read-only views of the configuration surface and system health. Changes go through `PATCH /api/config` (Platform
 * Owner), so every edit is validated and audited server-side; these screens only show the values in force. */

const CONFIG_SCREEN = { kind: "config", entity_ids: {}, selected_item: null } as const;
const HEALTH_SCREEN = { kind: "health", entity_ids: {}, selected_item: null } as const;
const RISK_PROFILES = ["conservative", "moderate", "growth", "aggressive"] as const;

function ApiNote({ children }: { children: ReactNode }) {
  return (
    <p className="text-ink-3">
      {children} See the{" "}
      <a className="underline" href="/docs" target="_blank" rel="noreferrer">
        API docs
      </a>
      .
    </p>
  );
}

export function ConfigPage() {
  usePublishScreen(CONFIG_SCREEN, "Config");
  const config = useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/config");
      if (error || !data) throw new Error("Could not load the configuration");
      return data;
    },
  });
  if (config.isPending) return <Empty>Loading…</Empty>;
  if (config.isError) return <ErrorLine>{config.error.message}</ErrorLine>;
  const c = config.data;
  const bands = c.tolerance_bands ?? {};
  const weights = c.priority_weights;
  const s = c.suitability;
  const t = c.approval_thresholds;

  return (
    <div className="space-y-3">
      <PageHeader
        title="Config"
        sub="The single configuration surface the engines read: Tolerance Bands, priority weights, tilt bound, SLA, approval thresholds and Suitability limits."
      />
      <ApiNote>
        Read-only here. The Platform Owner changes it with PATCH /api/config, and the next Analysis Run uses it.
      </ApiNote>
      <div className="grid items-start gap-3 lg:grid-cols-2">
        <Panel title="Tolerance Bands and Suitability limits by Risk Profile" label="Tolerance Bands" flush>
          <table className="grid-table">
            <thead>
              <tr>
                <th>Risk Profile</th>
                <th className="num">Drift warn</th>
                <th className="num">Drift breach</th>
                <th className="num">Max equity</th>
                <th className="num">Min cash</th>
              </tr>
            </thead>
            <tbody>
              {RISK_PROFILES.map((rp) => (
                <tr key={rp}>
                  <td className="capitalize">{rp}</td>
                  <td className="num">{bands[rp] ? `${bands[rp].warn} pp` : "n/a"}</td>
                  <td className="num">{bands[rp] ? `${bands[rp].breach} pp` : "n/a"}</td>
                  <td className="num">
                    {s?.max_equity_pct?.[rp] !== undefined ? pct(s.max_equity_pct[rp], 0) : "n/a"}
                  </td>
                  <td className="num">{s?.min_cash_pct?.[rp] !== undefined ? pct(s.min_cash_pct[rp], 0) : "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Priority, research and approvals" label="Priority and approvals">
          <dl className="grid grid-cols-[14rem_1fr] gap-y-1">
            <dt className="text-ink-3">Priority weights</dt>
            <dd className="mono">
              {weights
                ? `drift ${weights.drift} · risk ${weights.risk} · opportunity ${weights.opportunity} · urgency ${weights.urgency}`
                : "n/a"}
            </dd>
            <dt className="text-ink-3">Review SLA</dt>
            <dd className="mono">{c.sla_days} days</dd>
            <dt className="text-ink-3">Research Tilt bound</dt>
            <dd className="mono">±{c.tilt_bound_pp} pp per sector or Asset Class</dd>
            <dt className="text-ink-3">Investment Committee when</dt>
            <dd className="mono">
              {t ? `turnover ≥ ${pct(t.turnover_pct, 0)} or any Trade Line ≥ ${pct(t.trade_line_pct, 0)}` : "n/a"}
            </dd>
            <dt className="text-ink-3">Single position limit</dt>
            <dd className="mono">{s ? pct(s.single_position_pct, 0) : "n/a"}</dd>
            <dt className="text-ink-3">Sector limit (look-through)</dt>
            <dd className="mono">{s ? pct(s.sector_pct, 0) : "n/a"}</dd>
            <dt className="text-ink-3">Short horizon</dt>
            <dd className="mono">
              {s ? `< ${s.horizon_short_years} years: equity ≤ ${pct(s.horizon_short_equity_max_pct, 0)}` : "n/a"}
            </dd>
            <dt className="text-ink-3">Taxable-gain warning</dt>
            <dd className="mono">{s ? `gain ≥ ${pct(s.taxable_gain_pct, 0)}` : "n/a"}</dd>
          </dl>
        </Panel>
      </div>
    </div>
  );
}

const STATUS_TONE = { ok: "pos", missing: "warn", unavailable: "warn", error: "neg" } as const;

export function HealthPage() {
  usePublishScreen(HEALTH_SCREEN, "Health");
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/health");
      if (error || !data) throw new Error("Could not load system health");
      return data;
    },
  });
  if (health.isPending) return <Empty>Loading…</Empty>;
  if (health.isError) return <ErrorLine>{health.error.message}</ErrorLine>;
  const h = health.data;
  const age = h.market_data.snapshot_age_hours;
  const rows = [
    { name: "Database", status: h.database.status, detail: "SQLite, reachable" },
    {
      name: "Market-data snapshot",
      status: h.market_data.status,
      detail: age === null || age === undefined ? "no snapshot" : `${(age / 24).toFixed(1)} days old`,
    },
    {
      name: "LLM",
      status: h.llm.status,
      detail: h.llm.mode === "recorded" ? "recorded mode: replays committed responses" : `${h.llm.mode} mode`,
    },
  ];
  return (
    <div className="space-y-3">
      <PageHeader title="Health" sub="Database, market-data snapshot age and LLM availability." />
      <ApiNote>The same check is GET /api/health, for monitoring.</ApiNote>
      <Panel title="Components" label="Health" flush>
        <table className="grid-table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>
                  <Pill tone={STATUS_TONE[r.status]}>{r.status}</Pill>
                </td>
                <td className="text-ink-2">{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
