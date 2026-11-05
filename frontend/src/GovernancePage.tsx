import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import { Empty, ErrorLine, Icon, PageHeader, Panel, Pill, ScoreDial } from "./ui";

const pct = (v: number | null) => (v === null ? "n/a" : `${(v * 100).toFixed(1)}%`);

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "pos" | "neg" }) {
  return (
    <div className="px-3 py-2">
      <p className="eyebrow">{label}</p>
      <p className={`mono text-[1.5385rem] font-semibold leading-tight ${tone === "neg" ? "text-neg" : tone === "pos" ? "text-pos" : ""}`}>{value}</p>
      {sub && <p className="text-ink-3">{sub}</p>}
    </div>
  );
}

export function GovernancePage({ canRunFixtures }: { canRunFixtures: boolean }) {
  const qc = useQueryClient();
  const gov = useQuery({
    queryKey: ["governance"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/governance");
      if (error || !data) throw new Error("Could not load governance data");
      return data;
    },
  });
  const run = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/governance/fixtures/run");
      if (error || !data) throw new Error("Fixture run failed");
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["governance"] }),
  });

  if (gov.isPending) return <Empty>Loading…</Empty>;
  if (gov.isError) return <ErrorLine>{gov.error.message}</ErrorLine>;
  const { model_card: card, prompt_log: log, quality: q, fixtures: fx } = gov.data;
  const passTone = q.pass_rate === null ? undefined : q.pass_rate >= 0.9 ? "pos" : "neg";

  return (
    <div className="space-y-3">
      <PageHeader title="Governance" sub="How the AI is configured, how often it is grounded, and whether the guardrails still catch bad output." />

      <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Panel title="Model card" label="Model card" aside={<Pill tone={card.llm_mode === "live" ? "pos" : "warn"}>{card.llm_mode}</Pill>}>
          <dl className="grid grid-cols-[11rem_1fr] gap-y-1">
            <dt className="text-ink-3">Model</dt><dd className="mono">{card.model}</dd>
            <dt className="text-ink-3">Mode</dt><dd>{card.llm_mode}</dd>
            <dt className="text-ink-3">Endpoint</dt><dd className="mono">{card.llm_endpoint}</dd>
            <dt className="text-ink-3">Temperature</dt><dd className="mono">{card.temperature}</dd>
            <dt className="text-ink-3">Research Tilt bound</dt><dd className="mono">±{card.tilt_bound_pp} pp</dd>
            <dt className="text-ink-3">Current prompts</dt><dd className="flex flex-wrap gap-1">{card.current_prompt_versions.map((v) => <Pill key={v} tone="ai">{v}</Pill>)}</dd>
          </dl>
          <ul className="mt-3 space-y-1 border-t border-line pt-2">
            {card.controls.map((c) => <li key={c} className="flex gap-1.5 text-ink-2"><span className="mt-0.5 text-pos"><Icon name="approvals" size={13} /></span>{c}</li>)}
          </ul>
        </Panel>

        <Panel title="AI quality: grounding" label="AI quality" flush>
          <div className="grid grid-cols-3 divide-x divide-line border-b border-line">
            <div className="flex items-center gap-2 px-3 py-2">
              {q.pass_rate !== null && <ScoreDial value={q.pass_rate * 100} tone={q.pass_rate >= 0.9 ? "pos" : q.pass_rate >= 0.7 ? "warn" : "neg"} size={84} label="Grounding pass rate" />}
              <div><p className="eyebrow">Pass rate</p><p className={`mono text-[1.5385rem] font-semibold leading-tight ${passTone === "neg" ? "text-neg" : passTone === "pos" ? "text-pos" : ""}`}>{pct(q.pass_rate)}</p><p className="text-ink-3">{q.checks} checks</p></div>
            </div>
            <Kpi label="Grounded" value={String(q.claims_grounded)} sub={`of ${q.claims_total} claims`} />
            <Kpi label="Ungrounded" value={String(q.claims_ungrounded)} sub="flagged, kept out of memos" tone={q.claims_ungrounded > 0 ? "neg" : undefined} />
          </div>
          {q.pass_rate !== null && (
            <div className="px-3 pt-2">
              <div className="gridtex flex h-2.5 overflow-hidden rounded-full p-px"><div className="rod" style={{ width: `${q.pass_rate * 100}%`, background: "linear-gradient(to bottom, #5fd1a0, #0b7a4b)", transition: "width 240ms ease-out" }} /></div>
            </div>
          )}
          <div className="p-3">
            {q.ungrounded_by_issue.length === 0 ? <p className="text-ink-2">No ungrounded claims recorded.</p> : (
              <table className="grid-table">
                <thead><tr><th>Ungrounded reason</th><th className="num">Count</th></tr></thead>
                <tbody>{q.ungrounded_by_issue.map((i) => <tr key={i.code}><td className="mono">{i.code}</td><td className="num">{i.count}</td></tr>)}</tbody>
              </table>
            )}
          </div>
        </Panel>
      </div>

      <Panel
        title="Adversarial fixtures" label="Adversarial fixtures"
        aside={canRunFixtures ? <button className="btn btn-primary btn-sm" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Running…" : "Run fixtures"}</button> : undefined}
        flush
      >
        {run.isError && <div className="p-3"><ErrorLine>{run.error.message}</ErrorLine></div>}
        {fx === null ? <Empty>No run yet. Fixtures replay a fabricated quote, a wrong number and an uncited asset call through the validator.</Empty> : (
          <>
            <p className="flex items-center gap-2 border-b border-line px-3 py-2">
              <Pill tone={fx.passed === fx.total ? "pos" : "neg"}>{fx.passed}/{fx.total} behaved as expected</Pill>
              <span className="text-ink-2">Run <span className="mono">#{fx.run_id}</span> by {fx.ran_by} at <span className="mono">{fx.ran_at}</span></span>
            </p>
            <table className="grid-table">
              <thead><tr><th>Fixture</th><th>Expected</th><th>Actual</th><th>Result</th></tr></thead>
              <tbody>
                {fx.results.map((r) => (
                  <tr key={r.name}>
                    <td title={r.description}><span className="font-medium">{r.name}</span><span className="block text-ink-3">{r.description}</span></td>
                    <td className="mono">{r.expected_codes.join(", ") || "passes"}</td>
                    <td className="mono">{r.actual_codes.join(", ") || "passes"}</td>
                    <td><Pill tone={r.caught ? "pos" : "neg"}>{r.caught ? "caught" : "MISSED"}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Panel>

      <Panel title="Prompt / version log" label="Prompt version log" flush>
        {log.length === 0 ? <Empty>No LLM calls recorded yet.</Empty> : (
          <table className="grid-table">
            <thead><tr><th>Prompt</th><th>Models</th><th className="num">Calls</th><th>First used</th><th>Last used</th></tr></thead>
            <tbody>
              {log.map((p) => (
                <tr key={p.prompt_version}>
                  <td className="mono font-semibold">{p.prompt_version}</td><td className="mono">{p.models.join(", ") || "none (failed)"}</td>
                  <td className="num">{p.calls}</td><td className="mono">{p.first_used}</td><td className="mono">{p.last_used}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
