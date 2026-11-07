import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { ExchangeDrawer } from "./ExchangeDrawer";
import { AskButton, usePublishScreen } from "./assistantScreen";
import { Citations, DeltaBar, Drawer, Empty, Icon, Pill, RULE_TONE, money, pp, type Tone } from "./ui";

type Detail = components["schemas"]["PortfolioDetail"];
type Rec = components["schemas"]["RecommendationOut"];
type Rule = components["schemas"]["RuleOut"];
type LineIn = components["schemas"]["TradeLineIn"];
type Research = NonNullable<Rec["research"]>;
type AiStep = Research["steps"][number];
type Action = "accept" | "reject" | "modify";

const STATUS_LABEL: Record<Rec["status"], string> = {
  pending_advisor: "Pending Advisor decision",
  pending_compliance: "Pending Compliance (rule breach)",
  pending_committee: "Pending Investment Committee (high-impact)",
  approved: "Approved: cleared to act outside this system",
  rejected: "Rejected",
  superseded: "Superseded",
};
const STATUS_TONE: Record<Rec["status"], Tone> = {
  pending_advisor: "info",
  pending_compliance: "warn",
  pending_committee: "warn",
  approved: "pos",
  rejected: "neg",
  superseded: "mute",
};

/** The Trade Lines. Selecting one (numbered from 1, as the Assistant names them) points the Assistant at that line. */
function Lines({
  rec,
  selected,
  onSelect,
}: {
  rec: Rec;
  selected: number | null;
  onSelect: (line: number | null) => void;
}) {
  return (
    <table className="grid-table">
      <thead>
        <tr>
          <th>
            <span className="sr-only">Ask the Assistant</span>
          </th>
          <th>Side</th>
          <th>Instrument</th>
          <th>Account</th>
          <th className="num">Qty</th>
          <th className="num">Amount</th>
          <th className="num">% of Portfolio</th>
        </tr>
      </thead>
      <tbody>
        {rec.trade_lines.map((line, i) => (
          <tr key={`${line.account_id}-${line.symbol}`}>
            <td>
              <AskButton
                pressed={selected === i + 1}
                onToggle={() => onSelect(selected === i + 1 ? null : i + 1)}
                what={`Trade Line ${i + 1}`}
              />
            </td>
            <td>
              <Pill tone={line.side === "sell" ? "neg" : "pos"}>{line.side}</Pill>
            </td>
            <td>
              <span className="mono font-semibold">{line.symbol}</span> <span className="text-ink-3">{line.name}</span>
            </td>
            <td className="mono">{line.account_id}</td>
            <td className="num">{line.quantity}</td>
            <td className="num">{money(line.amount)}</td>
            <td className="num">
              <span className="inline-flex items-center gap-2">
                <DeltaBar
                  value={line.side === "sell" ? -line.pct_of_portfolio : line.pct_of_portfolio}
                  max={Math.max(5, ...rec.trade_lines.map((x) => x.pct_of_portfolio))}
                  width="5.5rem"
                />
                {line.pct_of_portfolio.toFixed(2)}%
              </span>
            </td>
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
      <p className="flex items-center gap-2 text-ink-2">
        Post-trade suitability <Pill tone={RULE_TONE[rec.suitability.status]}>{rec.suitability.status}</Pill>
      </p>
      {shown.length === 0 ? (
        <p className="text-ink-2">All seven Suitability Rules pass after these Trade Lines.</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {shown.map((r) => (
            <li key={r.rule_id} className="panel px-2 py-1">
              <span className="mono text-ink-3">{r.rule_id}</span> <span className="font-medium">{r.name}</span>{" "}
              <Pill tone={RULE_TONE[r.status]}>{r.status}</Pill>
              <p className="text-ink-2">{r.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Proposed (hollow) vs allowed (solid) tilt on a track; the shaded span is the engine's ± bound. */
function TiltTrack({ proposed, allowed, bound }: { proposed: number; allowed: number; bound: number }) {
  const scale = Math.max(bound, Math.abs(proposed), Math.abs(allowed)) * 1.15;
  const at = (v: number) => `${50 + (v / scale) * 50}%`;
  return (
    <div
      className="relative h-4 w-44"
      role="img"
      aria-label={`Proposed ${pp(proposed)}, allowed ${pp(allowed)}, bound ±${bound} pp`}
    >
      <div className="absolute inset-y-1 left-0 right-0 rounded-full bg-sunken" />
      <div
        className="absolute inset-y-1 rounded-full bg-ai-bg ring-1 ring-[#a3d6d0]"
        style={{ left: at(-bound), width: `${(bound / scale) * 100}%` }}
        title={`Allowed range ±${bound} pp`}
      />
      <div className="absolute inset-y-0 w-px bg-ink-3" style={{ left: "50%" }} />
      <div
        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 border-2 border-ink bg-surface"
        style={{ left: at(proposed) }}
        title={`AI proposed ${pp(proposed)}`}
      />
      <div
        className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ai"
        style={{ left: at(allowed) }}
        title={`Engine allowed ${pp(allowed)}`}
      />
    </div>
  );
}

const STEP_LABEL: Record<AiStep["step"], string> = { tilt: "Research Tilt", memo: "Rationale and memo" };

/** One line per AI step: how far to rely on it. Figures only; the prompt and reply text stay with `llm:read` reviewers. */
function StepSummary({ step, onOpen }: { step: AiStep; onOpen: (id: number) => void }) {
  const failed = step.outcome === "failed";
  const counts = step.grounded !== null && step.ungrounded !== null;
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-medium text-ink">{STEP_LABEL[step.step]}</span>
      <Pill tone={step.mode === "live" ? "ai" : "mute"}>{step.mode === "live" ? "live" : "recorded"}</Pill>
      {failed ? (
        <Pill tone="neg">
          <Icon name="alert" size={11} />
          failed
        </Pill>
      ) : (
        <Pill tone="pos">ok</Pill>
      )}
      <span className="mono text-ink-3">
        {step.latency_ms === null ? "n/a (replayed)" : `${step.latency_ms} ms`}
        {counts && !failed && ` · ${step.grounded} grounded · ${step.ungrounded} ungrounded`}
      </span>
      {failed && step.reason && <span className="text-ink-2">{step.reason}</span>}
      {step.exchange_id !== null && (
        <button type="button" className="btn btn-sm" onClick={() => onOpen(step.exchange_id!)}>
          Open exchange
        </button>
      )}
    </li>
  );
}

function ResearchSection({ research }: { research: Research }) {
  const { tilt, narrative, steps } = research;
  const [exchangeId, setExchangeId] = useState<number | null>(null);
  const grounded = narrative?.claims.filter((c) => c.grounded).length ?? 0;
  const ungrounded = (narrative?.claims.length ?? 0) - grounded;
  return (
    <section className="callout callout-ai !block space-y-3 !bg-surface" aria-label="AI contribution">
      <h3 className="flex flex-wrap items-center gap-2 !text-ink">
        <Pill tone="ai">
          <Icon name="spark" size={10} />
          AI contribution
        </Pill>
        <span className="font-normal text-ink-2">
          The AI proposes and explains; the engine owns every number and compliance outcome.
        </span>
      </h3>

      {steps.length > 0 && (
        <ul className="space-y-1" aria-label="AI steps">
          {steps.map((st) => (
            <StepSummary key={st.step} step={st} onOpen={setExchangeId} />
          ))}
        </ul>
      )}

      {tilt &&
        (tilt.status === "failed" ? (
          <p role="status" className="callout callout-warn">
            The AI Research Tilt was unavailable, so this is the plain rule-based Recommendation.
          </p>
        ) : tilt.entries.length === 0 ? (
          <p className="text-ink-2">The AI proposed no Research Tilt from the approved Insights.</p>
        ) : (
          <div>
            <table className="grid-table text-ink" aria-label="Research Tilt">
              <thead>
                <tr>
                  <th>Subject</th>
                  <th className="num">Exposure</th>
                  <th>Proposed ◇ vs allowed ● (±{tilt.bound_pp} pp)</th>
                  <th className="num">AI proposed</th>
                  <th className="num">Engine allowed</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {tilt.entries.map((e) => (
                  <tr key={`${e.subject_kind}-${e.subject}`}>
                    <td>
                      {e.subject}{" "}
                      <span className="text-ink-3">{e.subject_kind === "sector" ? "sector" : "asset class"}</span>
                    </td>
                    <td className="num">{e.exposure_pct.toFixed(1)}%</td>
                    <td>
                      <TiltTrack proposed={e.proposed_pp} allowed={e.allowed_pp} bound={tilt.bound_pp} />
                    </td>
                    <td className="num">{pp(e.proposed_pp)}</td>
                    <td className="num">
                      {e.clipped ? (
                        <span className="inline-flex items-center gap-1">
                          <Pill tone="warn">clipped</Pill>
                          <strong>{pp(e.allowed_pp)}</strong>
                        </span>
                      ) : (
                        pp(e.allowed_pp)
                      )}
                    </td>
                    <td className="text-ink-2">
                      AI proposed {pp(e.proposed_pp)}, engine allowed {pp(e.allowed_pp)}: {e.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-[0.8461rem] text-ink-3">
              Bound ±{tilt.bound_pp} pp ·{" "}
              <span className="mono">
                {tilt.model} · {tilt.prompt_version}
              </span>
            </p>
          </div>
        ))}

      {narrative &&
        (narrative.status === "failed" ? (
          <p role="status" className="callout callout-warn">
            The AI rationale and memo were unavailable for this Recommendation.
          </p>
        ) : (
          <>
            <div>
              <h4 className="mb-1 flex items-center gap-2 font-semibold">
                Grounding inspector
                <Pill tone="pos">
                  <Icon name="approvals" size={11} />
                  {grounded} verified
                </Pill>
                {ungrounded > 0 && (
                  <Pill tone="neg">
                    <Icon name="alert" size={11} />
                    {ungrounded} ungrounded
                  </Pill>
                )}
              </h4>
              <ul className="space-y-1.5">
                {narrative.claims.map((c) => (
                  <li
                    key={c.index}
                    className={`rounded-xl border px-2 py-1.5 ${c.grounded ? "border-line bg-surface" : "border-[#f1b8b3] bg-neg-bg"}`}
                  >
                    <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
                      <Pill tone={c.grounded ? "pos" : "neg"}>
                        <Icon name={c.grounded ? "approvals" : "alert"} size={11} />
                        {c.grounded ? "grounded" : "ungrounded: excluded from memo"}
                      </Pill>
                      <span className="min-w-0 flex-1 text-ink">{c.text}</span>
                    </div>
                    <div className="mt-1">
                      <Citations citations={c.citations} />
                    </div>
                    {c.issues.map((i) => (
                      <p key={i.code + i.message} className="mt-0.5 flex items-center gap-1 text-neg">
                        <Icon name="alert" size={12} />
                        {i.message}
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="mb-1 font-semibold">
                Advisor memo <span className="font-normal text-ink-3">(grounded claims only)</span>
              </h4>
              <pre className="whitespace-pre-wrap rounded-xl border border-line bg-sunken p-2 font-sans text-ink">
                {narrative.memo}
              </pre>
              <p className="text-[0.8461rem] text-ink-3">
                <span className="mono">
                  {narrative.model} · {narrative.prompt_version}
                </span>
              </p>
            </div>
          </>
        ))}
      {exchangeId !== null && <ExchangeDrawer id={exchangeId} canLineage={false} onClose={() => setExchangeId(null)} />}
    </section>
  );
}

/* ---------- trade modification drawer ---------- */
function ModifyEditor({
  rec,
  accounts,
  lines,
  onChange,
}: {
  rec: Rec;
  accounts: string[];
  lines: LineIn[];
  onChange: (l: LineIn[]) => void;
}) {
  const patch = (i: number, p: Partial<LineIn>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...p } : l)));
  const names = Object.fromEntries(rec.trade_lines.map((l) => [l.symbol, l.name]));
  return (
    <div className="space-y-2">
      <p className="callout callout-info">
        Edit the full set of Trade Lines. The Suitability Rules re-run as soon as you submit, and the result is saved as
        a new linked version.
      </p>
      <table className="grid-table">
        <thead>
          <tr>
            <th>Side</th>
            <th>Symbol</th>
            <th>Account</th>
            <th className="num">Quantity</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td>
                <select
                  aria-label="Side"
                  className="field"
                  value={l.side}
                  onChange={(e) => patch(i, { side: e.target.value as LineIn["side"] })}
                >
                  <option value="buy">buy</option>
                  <option value="sell">sell</option>
                </select>
              </td>
              <td>
                <input
                  aria-label="Symbol"
                  className="field mono w-24"
                  value={l.symbol}
                  title={names[l.symbol]}
                  onChange={(e) => patch(i, { symbol: e.target.value.toUpperCase() })}
                />
              </td>
              <td>
                <select
                  aria-label="Account"
                  className="field mono"
                  value={l.account_id}
                  onChange={(e) => patch(i, { account_id: e.target.value })}
                >
                  {accounts.map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </td>
              <td className="num">
                <input
                  aria-label="Quantity"
                  type="number"
                  min={1}
                  className="field mono w-28 text-right"
                  value={l.quantity}
                  onChange={(e) => patch(i, { quantity: Math.trunc(Number(e.target.value)) })}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onChange(lines.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => onChange([...lines, { account_id: accounts[0], symbol: "", side: "buy", quantity: 1 }])}
      >
        Add Trade Line
      </button>
    </div>
  );
}

function DecisionForm({
  rec,
  accounts,
  portfolioId,
  onModified,
}: {
  rec: Rec;
  accounts: string[];
  portfolioId: string;
  onModified: (b: Rule[]) => void;
}) {
  const qc = useQueryClient();
  const formId = useId();
  const [action, setAction] = useState<Action>("accept");
  const [rationale, setRationale] = useState("");
  const [lines, setLines] = useState<LineIn[]>(
    rec.trade_lines.map(({ account_id, symbol, side, quantity }) => ({ account_id, symbol, side, quantity })),
  );
  const [drawer, setDrawer] = useState(false);
  const decide = useMutation({
    mutationFn: async () => {
      const body = { action, rationale: rationale.trim() || null, trade_lines: action === "modify" ? lines : null };
      const { data, error } = await api.POST("/api/recommendations/{recommendation_id}/decision", {
        params: { path: { recommendation_id: rec.id } },
        body,
      });
      if (!data) {
        const detail = (error as { detail?: unknown } | undefined)?.detail;
        throw new Error(typeof detail === "string" ? detail : "Could not record the Decision");
      }
      return data;
    },
    onSuccess: (r) => {
      onModified(r.new_breaches);
      setRationale("");
      setDrawer(false);
      qc.invalidateQueries({ queryKey: ["portfolio", portfolioId] });
    },
  });
  const needsWhy = action !== "accept";
  const choose = (a: Action) => {
    setAction(a);
    setDrawer(a === "modify");
  };
  const submit = (
    <>
      <label className="label">
        Rationale{" "}
        {needsWhy ? (
          <span className="text-neg">(required)</span>
        ) : (
          <span className="font-normal text-ink-3">(optional)</span>
        )}
        <textarea className="field" rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} />
      </label>
      <button
        form={formId}
        className="btn btn-primary"
        disabled={decide.isPending || (needsWhy && !rationale.trim()) || (action === "modify" && lines.length === 0)}
      >
        Record Decision
      </button>
      {decide.isError && (
        <p role="alert" className="callout callout-neg">
          {decide.error.message}
        </p>
      )}
    </>
  );
  return (
    <form
      id={formId}
      className="panel space-y-2 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        decide.mutate();
      }}
      aria-label="Decision"
    >
      <div className="seg" role="group" aria-label="Decision action">
        {(["accept", "modify", "reject"] as const).map((a) => (
          <button key={a} type="button" aria-pressed={action === a} onClick={() => choose(a)} className="capitalize">
            {a}
          </button>
        ))}
      </div>
      {action === "modify" ? (
        <button type="button" className="btn btn-sm block" onClick={() => setDrawer(true)}>
          Edit Trade Lines ({lines.length})…
        </button>
      ) : (
        submit
      )}
      {drawer && (
        <Drawer title="Modify Trade Lines" onClose={() => setDrawer(false)}>
          <ModifyEditor rec={rec} accounts={accounts} lines={lines} onChange={setLines} />
          <div className="space-y-2 border-t border-line pt-3">{submit}</div>
        </Drawer>
      )}
    </form>
  );
}

export function RecommendationPanel({ p, canDecide }: { p: Detail; canDecide: boolean }) {
  const rec = p.recommendation;
  const accounts = [...new Set(p.holdings.map((h) => h.account_id))].sort();
  const [newBreaches, setNewBreaches] = useState<Rule[]>([]);
  // Kept per version: a Trade Line number means nothing on another version's lines.
  const [selected, setSelected] = useState<{ recId: number; line: number } | null>(null);
  const line = rec && selected?.recId === rec.id ? selected.line : null;
  usePublishScreen(
    rec
      ? {
          kind: "recommendation",
          entity_ids: { recommendation_id: String(rec.id), portfolio_id: rec.portfolio_id },
          selected_item: line ? `trade_line:${line}` : null,
        }
      : null,
    rec ? `Recommendation ${rec.id}${line ? `, Trade Line ${line}` : ""}` : "",
  );
  return (
    <div className="space-y-3">
      <p className="callout callout-info">
        <Icon name="lock" size={14} />
        Nothing is executed from this system. Approved means the Recommendation is cleared to act on outside this
        system.
      </p>
      {newBreaches.length > 0 && (
        <div role="alert" className="callout callout-neg !block">
          <p className="font-semibold">
            Compliance impact: the modified version breaches{" "}
            {newBreaches.length === 1 ? "a Suitability Rule" : "Suitability Rules"} the earlier version did not, so it
            now needs Compliance sign-off.
          </p>
          <ul className="list-disc pl-5">
            {newBreaches.map((r) => (
              <li key={r.rule_id}>
                <span className="mono">{r.rule_id}</span> {r.name}: {r.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!rec ? (
        <Empty>
          {p.drift
            ? "No Recommendation: every Asset Class is within its Tolerance Band."
            : "No analysis run yet; run an analysis from the queue."}
        </Empty>
      ) : (
        <>
          <div>
            <p className="flex flex-wrap items-center gap-2">
              <strong>Version {rec.version}</strong>
              <span aria-label="Recommendation status">
                <Pill tone={STATUS_TONE[rec.status]}>{STATUS_LABEL[rec.status]}</Pill>
              </span>
              <span className="text-ink-2">
                turnover <span className="mono">{rec.turnover_pct.toFixed(1)}%</span> of{" "}
                <span className="mono">{money(rec.total_value)}</span> · by {rec.created_by}
              </span>
            </p>
            <p className="text-ink-2">{rec.summary}</p>
          </div>
          {(rec.status === "pending_advisor" ||
            rec.status === "pending_compliance" ||
            rec.status === "pending_committee") && (
            <p className="text-ink-2">
              Approval path: {rec.approval.required_steps.join(" → ")} → Approved.
              {rec.approval.reasons.map((x) => (
                <span key={x} className="block font-medium text-warn">
                  {x}
                </span>
              ))}
            </p>
          )}
          <div className="panel overflow-hidden">
            <Lines rec={rec} selected={line} onSelect={(n) => setSelected(n ? { recId: rec.id, line: n } : null)} />
          </div>
          <PostTradeRules rec={rec} />
          {rec.research && <ResearchSection research={rec.research} />}
          {rec.status === "pending_advisor" && canDecide && (
            <DecisionForm
              key={rec.id}
              rec={rec}
              accounts={accounts}
              portfolioId={p.portfolio_id}
              onModified={setNewBreaches}
            />
          )}
        </>
      )}
      <div>
        <h3 className="mb-1 font-semibold">Version history</h3>
        {p.history.versions.length === 0 ? (
          <Empty>No Recommendations yet.</Empty>
        ) : (
          <ol className="space-y-1.5 border-l-2 border-line pl-3">
            {p.history.versions.map((v) => (
              <li key={v.id}>
                <span className="mono font-semibold">v{v.version}</span>{" "}
                <Pill tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Pill>{" "}
                <span className="text-ink-2">
                  {v.created_at.slice(0, 16).replace("T", " ")} · by {v.created_by}
                </span>
                {v.parent_id && <span className="text-ink-3"> · modified from #{v.parent_id}</span>}{" "}
                <Pill tone={RULE_TONE[v.suitability_status]}>{v.suitability_status}</Pill>
                <ul className="ml-4 list-disc text-ink-2">
                  {p.history.decisions
                    .filter((d) => d.recommendation_id === v.id)
                    .map((d) => (
                      <li key={d.id}>
                        {d.action.replace("_", " ")} by {d.actor_name} ({d.actor_role})
                        {d.rationale ? `: ${d.rationale}` : ""}
                      </li>
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
