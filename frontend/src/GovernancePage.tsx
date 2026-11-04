import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";

const pct = (v: number | null) => (v === null ? "n/a" : `${(v * 100).toFixed(1)}%`);

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

  if (gov.isPending) return <p>Loading…</p>;
  if (gov.isError) return <p role="alert" className="text-red-600">{gov.error.message}</p>;
  const { model_card: card, prompt_log: log, quality: q, fixtures: fx } = gov.data;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Governance</h1>

      <section className="rounded border p-4" aria-label="Model card">
        <h2 className="mb-2 font-semibold">Model card</h2>
        <dl className="grid grid-cols-[12rem_1fr] gap-y-1 text-sm">
          <dt className="text-slate-500">Model</dt><dd>{card.model}</dd>
          <dt className="text-slate-500">Mode</dt><dd>{card.llm_mode}</dd>
          <dt className="text-slate-500">Endpoint</dt><dd>{card.llm_endpoint}</dd>
          <dt className="text-slate-500">Temperature</dt><dd>{card.temperature}</dd>
          <dt className="text-slate-500">Research Tilt bound</dt><dd>±{card.tilt_bound_pp} pp</dd>
          <dt className="text-slate-500">Current prompts</dt><dd>{card.current_prompt_versions.join(", ")}</dd>
        </dl>
        <ul className="mt-3 list-disc pl-5 text-sm">{card.controls.map((c) => <li key={c}>{c}</li>)}</ul>
      </section>

      <section className="rounded border p-4" aria-label="AI quality">
        <h2 className="mb-2 font-semibold">AI quality: grounding</h2>
        <p className="text-sm">
          Pass rate <strong>{pct(q.pass_rate)}</strong> · {q.claims_grounded} grounded / {q.claims_ungrounded} ungrounded of {q.claims_total} claims
          across {q.checks} checks
        </p>
        {q.ungrounded_by_issue.length > 0 && (
          <table className="mt-2 text-sm">
            <thead><tr><th className="pr-6 text-left">Ungrounded reason</th><th className="text-right">Count</th></tr></thead>
            <tbody>{q.ungrounded_by_issue.map((i) => <tr key={i.code}><td className="pr-6">{i.code}</td><td className="text-right">{i.count}</td></tr>)}</tbody>
          </table>
        )}
      </section>

      <section className="rounded border p-4" aria-label="Adversarial fixtures">
        <div className="mb-2 flex items-center gap-4">
          <h2 className="font-semibold">Adversarial fixtures</h2>
          {canRunFixtures && (
            <button className="rounded bg-slate-800 px-3 py-1 text-sm text-white" onClick={() => run.mutate()} disabled={run.isPending}>
              Run fixtures
            </button>
          )}
        </div>
        {run.isError && <p role="alert" className="text-red-600">{run.error.message}</p>}
        {fx === null ? <p className="text-sm text-slate-600">No run yet.</p> : (
          <>
            <p className="text-sm">
              Run #{fx.run_id} by {fx.ran_by} at {fx.ran_at}: <strong>{fx.passed}/{fx.total}</strong> behaved as expected
            </p>
            <table className="mt-2 text-sm">
              <thead><tr><th className="pr-6 text-left">Fixture</th><th className="pr-6 text-left">Expected</th><th className="pr-6 text-left">Actual</th><th>Result</th></tr></thead>
              <tbody>
                {fx.results.map((r) => (
                  <tr key={r.name}>
                    <td className="pr-6" title={r.description}>{r.name}</td>
                    <td className="pr-6">{r.expected_codes.join(", ") || "passes"}</td>
                    <td className="pr-6">{r.actual_codes.join(", ") || "passes"}</td>
                    <td className={r.caught ? "text-green-700" : "text-red-700"}>{r.caught ? "caught" : "MISSED"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="rounded border p-4" aria-label="Prompt version log">
        <h2 className="mb-2 font-semibold">Prompt / version log</h2>
        {log.length === 0 ? <p className="text-sm text-slate-600">No LLM calls recorded yet.</p> : (
          <table className="text-sm">
            <thead><tr><th className="pr-6 text-left">Prompt</th><th className="pr-6 text-left">Models</th><th className="pr-6 text-right">Calls</th><th className="pr-6 text-left">First used</th><th className="text-left">Last used</th></tr></thead>
            <tbody>
              {log.map((p) => (
                <tr key={p.prompt_version}>
                  <td className="pr-6">{p.prompt_version}</td><td className="pr-6">{p.models.join(", ") || "none (failed)"}</td>
                  <td className="pr-6 text-right">{p.calls}</td><td className="pr-6">{p.first_used}</td><td>{p.last_used}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
