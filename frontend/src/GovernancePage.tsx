import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment } from "react";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { usePublishScreen } from "./assistantScreen";
import { Empty, ErrorLine, Icon, PageHeader, Panel, Pill, ScoreDial } from "./ui";

const pct = (v: number | null) => (v === null ? "n/a" : `${(v * 100).toFixed(1)}%`);

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "pos" | "neg" }) {
  return (
    <div className="px-3 py-2">
      <p className="eyebrow">{label}</p>
      <p
        className={`mono text-[1.5385rem] font-semibold leading-tight ${tone === "neg" ? "text-neg" : tone === "pos" ? "text-pos" : ""}`}
      >
        {value}
      </p>
      {sub && <p className="text-ink-3">{sub}</p>}
    </div>
  );
}

const GOVERNANCE_SCREEN = { kind: "governance", entity_ids: {}, selected_item: null } as const;

export function GovernancePage({ canRunFixtures }: { canRunFixtures: boolean }) {
  const qc = useQueryClient();
  usePublishScreen(GOVERNANCE_SCREEN, "Governance");
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
  const { model_card: card, prompt_log: log, quality: q, fixtures: fx, capture_health: ch } = gov.data;
  const passTone = q.pass_rate === null ? undefined : q.pass_rate >= 0.9 ? "pos" : "neg";

  return (
    <div className="space-y-3">
      <PageHeader
        title="Governance"
        sub="How the AI is configured, how often it is grounded, and whether the guardrails still catch bad output."
      />

      <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Panel
          title="Model card"
          label="Model card"
          aside={<Pill tone={card.llm_mode === "live" ? "pos" : "warn"}>{card.llm_mode}</Pill>}
        >
          <dl className="grid grid-cols-[11rem_1fr] gap-y-1">
            <dt className="text-ink-3">Model</dt>
            <dd className="mono">{card.model}</dd>
            <dt className="text-ink-3">Mode</dt>
            <dd>{card.llm_mode}</dd>
            <dt className="text-ink-3">Endpoint</dt>
            <dd className="mono">{card.llm_endpoint}</dd>
            <dt className="text-ink-3">Temperature</dt>
            <dd className="mono">{card.temperature ?? "provider default (not sent)"}</dd>
            <dt className="text-ink-3">Research Tilt bound</dt>
            <dd className="mono">±{card.tilt_bound_pp} pp</dd>
            <dt className="text-ink-3">Current prompts</dt>
            <dd className="flex flex-wrap gap-1">
              {card.current_prompt_versions.map((v) => (
                <Pill key={v} tone="ai">
                  {v}
                </Pill>
              ))}
            </dd>
          </dl>
          <ul className="mt-3 space-y-1 border-t border-line pt-2">
            {card.controls.map((c) => (
              <li key={c} className="flex gap-1.5 text-ink-2">
                <span className="mt-0.5 text-pos">
                  <Icon name="approvals" size={13} />
                </span>
                {c}
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="AI quality: grounding" label="AI quality" flush>
          <div className="grid grid-cols-3 divide-x divide-line border-b border-line">
            <div className="flex items-center gap-2 px-3 py-2">
              {q.pass_rate !== null && (
                <ScoreDial
                  value={q.pass_rate * 100}
                  tone={q.pass_rate >= 0.9 ? "pos" : q.pass_rate >= 0.7 ? "warn" : "neg"}
                  size={84}
                  label="Grounding pass rate"
                />
              )}
              <div>
                <p className="eyebrow">Pass rate</p>
                <p
                  className={`mono text-[1.5385rem] font-semibold leading-tight ${passTone === "neg" ? "text-neg" : passTone === "pos" ? "text-pos" : ""}`}
                >
                  {pct(q.pass_rate)}
                </p>
                <p className="text-ink-3">{q.checks} checks</p>
              </div>
            </div>
            <Kpi label="Grounded" value={String(q.claims_grounded)} sub={`of ${q.claims_total} claims`} />
            <Kpi
              label="Ungrounded"
              value={String(q.claims_ungrounded)}
              sub="flagged, kept out of memos"
              tone={q.claims_ungrounded > 0 ? "neg" : undefined}
            />
          </div>
          {q.pass_rate !== null && (
            <div className="px-3 pt-2">
              <div className="gridtex flex h-2.5 overflow-hidden rounded-full p-px">
                <div
                  className="rod"
                  style={{
                    width: `${q.pass_rate * 100}%`,
                    background: "linear-gradient(to bottom, #5fd1a0, #0b7a4b)",
                    transition: "width 240ms ease-out",
                  }}
                />
              </div>
            </div>
          )}
          <div className="p-3">
            {q.ungrounded_by_issue.length === 0 ? (
              <p className="text-ink-2">No ungrounded claims recorded.</p>
            ) : (
              <table className="grid-table">
                <thead>
                  <tr>
                    <th>Ungrounded reason</th>
                    <th className="num">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {q.ungrounded_by_issue.map((i) => (
                    <tr key={i.code}>
                      <td className="mono">{i.code}</td>
                      <td className="num">{i.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Panel>
      </div>

      <Panel
        title="Capture health"
        label="Capture health"
        flush
        aside={
          <Pill tone={ch.unreferenced > 0 ? "warn" : "pos"}>
            {ch.unreferenced > 0 ? "Unanchored Exchanges" : "All Exchanges anchored"}
          </Pill>
        }
      >
        <div className="grid grid-cols-2 divide-x divide-line sm:grid-cols-5">
          <Kpi label="Exchanges" value={String(ch.total)} sub="stored, append-only" />
          <Kpi label="Live" value={String(ch.live)} sub="crossed the wire" />
          <Kpi label="Recorded" value={String(ch.recorded)} sub="replayed" />
          <Kpi
            label="Errors"
            value={String(ch.errors)}
            sub="failed calls, kept"
            tone={ch.errors > 0 ? "neg" : undefined}
          />
          <Kpi
            label="Unreferenced"
            value={String(ch.unreferenced)}
            sub="no Audit Event points here"
            tone={ch.unreferenced > 0 ? "neg" : undefined}
          />
        </div>
        <div className="grid grid-cols-2 divide-x divide-line border-t border-line sm:grid-cols-5">
          <Kpi
            label="Trajectories"
            value={String(ch.trajectories)}
            sub="ordered model requests, one per call or Answer"
          />
          <Kpi
            label="Turns using lookups"
            value={ch.lookup_share === null ? "—" : `${Math.round(ch.lookup_share * 100)}%`}
            sub={`${ch.assistant_turns_with_lookups} of ${ch.assistant_turns} Assistant turns`}
          />
        </div>
      </Panel>

      <Panel
        title="Adversarial fixtures"
        label="Adversarial fixtures"
        aside={
          canRunFixtures ? (
            <button className="btn btn-primary btn-sm" onClick={() => run.mutate()} disabled={run.isPending}>
              {run.isPending ? "Running…" : "Run fixtures"}
            </button>
          ) : undefined
        }
        flush
      >
        {run.isError && (
          <div className="p-3">
            <ErrorLine>{run.error.message}</ErrorLine>
          </div>
        )}
        {fx === null ? (
          <Empty>
            No run yet. Fixtures replay a fabricated quote, a wrong number and an uncited asset call through the
            validator.
          </Empty>
        ) : (
          <>
            <p className="flex items-center gap-2 border-b border-line px-3 py-2">
              <Pill tone={fx.passed === fx.total ? "pos" : "neg"}>
                {fx.passed}/{fx.total} behaved as expected
              </Pill>
              <span className="text-ink-2">
                Run <span className="mono">#{fx.run_id}</span> by {fx.ran_by} at{" "}
                <span className="mono">{fx.ran_at}</span>
              </span>
            </p>
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Fixture</th>
                  <th>Expected</th>
                  <th>Actual</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {fx.results.map((r) => (
                  <tr key={r.name}>
                    <td title={r.description}>
                      <span className="font-medium">{r.name}</span>
                      <span className="block text-ink-3">{r.description}</span>
                    </td>
                    <td className="mono">{r.expected_codes.join(", ") || "passes"}</td>
                    <td className="mono">{r.actual_codes.join(", ") || "passes"}</td>
                    <td>
                      <Pill tone={r.caught ? "pos" : "neg"}>{r.caught ? "caught" : "MISSED"}</Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Panel>

      <AssistantPanel assistant={card.assistant} />

      <Panel title="Prompt / version log" label="Prompt version log" flush>
        {log.length === 0 ? (
          <Empty>No LLM calls recorded yet.</Empty>
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th>Prompt</th>
                <th>Models</th>
                <th className="num">Calls</th>
                <th>First used</th>
                <th>Last used</th>
              </tr>
            </thead>
            <tbody>
              {log.map((p) => (
                <tr key={p.prompt_version}>
                  <td className="mono font-semibold">{p.prompt_version}</td>
                  <td className="mono">{p.models.join(", ") || "none (failed)"}</td>
                  <td className="num">{p.calls}</td>
                  <td className="mono">{p.first_used}</td>
                  <td className="mono">{p.last_used}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

type AssistantCard = components["schemas"]["AssistantCard"];

const LIMITS: [keyof AssistantCard["limits"], string, string][] = [
  ["question_max_chars", "Question length", "characters"],
  ["questions_per_conversation", "Per Conversation", "Questions"],
  ["questions_per_hour", "Per user per hour", "Questions"],
  ["history_pairs", "History sent", "Question/Answer pairs"],
  ["context_rows", "List rows sent", "rows"],
  ["request_limit", "Model requests per Answer", "requests"],
];

function AssistantPanel({ assistant }: { assistant: AssistantCard }) {
  const latest = assistant.latest_eval;
  const stale = latest !== null && latest.prompt_version !== assistant.prompt_version;
  return (
    <Panel
      title="Assistant"
      label="Assistant"
      flush
      aside={
        <Pill tone="ai">
          <span className="mono">{assistant.prompt_version}</span>
        </Pill>
      }
    >
      <div className="grid gap-3 p-3 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <ul className="space-y-1">
          {assistant.scope_policy.map((rule) => (
            <li key={rule} className="flex gap-1.5 text-ink-2">
              <span className="mt-0.5 text-pos">
                <Icon name="approvals" size={13} />
              </span>
              {rule}
            </li>
          ))}
        </ul>
        <dl className="grid grid-cols-[11rem_1fr] content-start gap-y-1">
          {LIMITS.map(([key, label, unit]) => (
            <Fragment key={key}>
              <dt className="text-ink-3">{label}</dt>
              <dd>
                <span className="mono">{assistant.limits[key].toLocaleString()}</span> {unit}
              </dd>
            </Fragment>
          ))}
        </dl>
      </div>
      <div className="border-t border-line">
        {latest === null ? (
          <Empty>
            No live eval results yet. Run <span className="mono">uv run python -m tests.fixtures.assistant_eval</span>{" "}
            and commit the results.
          </Empty>
        ) : (
          <>
            <p className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
              <span className="eyebrow">Latest live eval</span>
              <Pill tone={latest.passed === latest.cases ? "pos" : "warn"}>
                {latest.passed}/{latest.cases} cases passed
              </Pill>
              {stale && <Pill tone="warn">run against {latest.prompt_version}</Pill>}
              <span className="text-ink-2">
                <span className="mono">{latest.model}</span> at <span className="mono">{latest.ran_at}</span>
              </span>
            </p>
            <div className="grid grid-cols-2 divide-x divide-line sm:grid-cols-5">
              <Kpi
                label="Refusal rate"
                value={pct(latest.refusal_rate)}
                sub="out-of-scope Questions the model refused"
              />
              <Kpi
                label="False refusals"
                value={pct(latest.false_refusal_rate)}
                sub="in-scope Questions refused"
                tone={latest.false_refusal_rate ? "neg" : undefined}
              />
              <Kpi
                label="Ungrounded Claims"
                value={pct(latest.ungrounded_claim_rate)}
                sub={`of ${latest.claims_total} Claims`}
                tone={latest.ungrounded_claim_rate ? "neg" : undefined}
              />
              <Kpi
                label="Failed turns"
                value={String(latest.failed_turns)}
                sub="unreadable or rejected"
                tone={latest.failed_turns > 0 ? "neg" : undefined}
              />
              <Kpi
                label="Injection leaks"
                value={String(latest.injection_leaks)}
                sub="injection cases obeyed or out of scope"
                tone={latest.injection_leaks > 0 ? "neg" : "pos"}
              />
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
