import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { AskButton, usePublishScreen } from "./assistantScreen";
import { Empty, ErrorLine, PageHeader, Pill, RULE_TONE, money } from "./ui";

type Item = components["schemas"]["ApprovalItem"];
type Step = "compliance" | "committee";

const TITLE: Record<Step, string> = { compliance: "Pending Compliance", committee: "Pending Investment Committee" };
const BLURB: Record<Step, string> = {
  compliance: "Recommendations with a Suitability Rule breach. Approving records an exception; blocking stops it.",
  committee: "High-impact Recommendations (turnover or single Trade Line at or above threshold).",
};
const ACTIONS: Record<Step, { action: string; label: string; danger?: boolean }[]> = {
  compliance: [
    { action: "approve", label: "Approve exception" },
    { action: "block", label: "Block", danger: true },
  ],
  committee: [
    { action: "approve", label: "Approve" },
    { action: "reject", label: "Reject", danger: true },
  ],
};

function StepForm({
  item,
  canCompliance,
  canCommittee,
}: {
  item: Item;
  canCompliance: boolean;
  canCommittee: boolean;
}) {
  const qc = useQueryClient();
  const [rationale, setRationale] = useState("");
  const [touched, setTouched] = useState(false);
  const allowed = item.step === "compliance" ? canCompliance : canCommittee;
  const decide = useMutation({
    mutationFn: async (action: string) => {
      const path = { params: { path: { recommendation_id: item.recommendation.id } } };
      const { data, error } =
        item.step === "compliance"
          ? await api.POST("/api/recommendations/{recommendation_id}/compliance", {
              ...path,
              body: { action: action as "approve" | "block", rationale },
            })
          : await api.POST("/api/recommendations/{recommendation_id}/committee", {
              ...path,
              body: { action: action as "approve" | "reject", rationale },
            });
      if (!data) {
        const detail = (error as { detail?: unknown } | undefined)?.detail;
        throw new Error(typeof detail === "string" ? detail : "Could not record the Decision");
      }
    },
    onSuccess: () => {
      setRationale("");
      setTouched(false);
      qc.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  if (!allowed) return null;
  const missing = !rationale.trim();
  return (
    <form
      className="space-y-2 border-t border-line pt-3"
      aria-label={`${item.step} decision`}
      onSubmit={(e) => e.preventDefault()}
    >
      <label className="label">
        Rationale <span className="text-neg">(required for every outcome)</span>
        <textarea
          className="field"
          rows={2}
          aria-invalid={touched && missing}
          value={rationale}
          onBlur={() => setTouched(true)}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Why is this exception acceptable, or why does it stay blocked?"
        />
      </label>
      {touched && missing && <p className="text-neg">A rationale is mandatory; it is recorded on the audit trail.</p>}
      <div className="flex gap-2">
        {(ACTIONS[item.step as Step] ?? []).map((a) => (
          <button
            key={a.action}
            type="button"
            className={`btn ${a.danger ? "btn-danger" : "btn-primary"}`}
            disabled={decide.isPending || missing}
            onClick={() => decide.mutate(a.action)}
          >
            {a.label}
          </button>
        ))}
      </div>
      {decide.isError && <ErrorLine>{decide.error.message}</ErrorLine>}
    </form>
  );
}

function ItemCard({
  item,
  canCompliance,
  canCommittee,
  selected,
  onSelect,
}: {
  item: Item;
  canCompliance: boolean;
  canCommittee: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const r = item.recommendation;
  return (
    <li className="panel space-y-3 p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <AskButton pressed={selected} onToggle={onSelect} what={`Recommendation ${r.id}`} />
        <Link className="mono font-semibold text-brand hover:underline" to={`/portfolios/${item.portfolio_id}`}>
          {item.portfolio_id}
        </Link>
        {item.client_name && <strong>{item.client_name}</strong>}
        <span className="capitalize text-ink-2">{item.risk_profile}</span>
        <span className="text-ink-2">
          version {r.version} · turnover <span className="mono">{r.turnover_pct.toFixed(1)}%</span> of{" "}
          <span className="mono">{money(r.total_value)}</span>
        </span>
        <span className="ml-auto text-ink-3">Required steps: {r.approval.required_steps.join(" → ")}</span>
      </div>
      <p className="text-ink-2">{r.summary}</p>
      {r.approval.reasons.length > 0 && (
        <div className="callout callout-warn !block">
          <p className="font-semibold">
            High-impact (thresholds: turnover <span className="mono">{r.approval.thresholds.turnover_pct}%</span>,
            single Trade Line <span className="mono">{r.approval.thresholds.trade_line_pct}%</span>)
          </p>
          <ul className="list-disc pl-5">
            {r.approval.reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="panel overflow-hidden">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Side</th>
                <th>Instrument</th>
                <th>Account</th>
                <th className="num">Qty</th>
                <th className="num">Amount</th>
                <th className="num">% of Portfolio</th>
              </tr>
            </thead>
            <tbody>
              {r.trade_lines.map((l) => (
                <tr key={`${l.account_id}-${l.symbol}`}>
                  <td>
                    <Pill tone={l.side === "sell" ? "neg" : "pos"}>{l.side}</Pill>
                  </td>
                  <td className="mono font-semibold">{l.symbol}</td>
                  <td className="mono">{l.account_id}</td>
                  <td className="num">{l.quantity}</td>
                  <td className="num">{money(l.amount)}</td>
                  <td className="num">{l.pct_of_portfolio.toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="space-y-2">
          <div>
            <h3 className="mb-1 font-semibold">Suitability flags</h3>
            {item.rules.length === 0 ? (
              <p className="text-ink-2">No warnings or breaches.</p>
            ) : (
              <ul className="space-y-1">
                {item.rules.map((rule) => (
                  <li key={rule.rule_id} className="rounded-xl border border-line px-2 py-1">
                    <span className="mono whitespace-nowrap text-ink-3">{rule.rule_id}</span>{" "}
                    <span className="font-medium">{rule.name}</span>{" "}
                    <Pill tone={RULE_TONE[rule.status as keyof typeof RULE_TONE] ?? "mute"}>{rule.status}</Pill>
                    <p className="text-ink-2">{rule.message}</p>
                    <ul className="ml-4 list-disc">
                      {rule.findings.map((f) => (
                        <li key={f.subject}>
                          <span className="mono">
                            {f.subject}: limit {f.limit}%, actual {f.actual}%
                          </span>{" "}
                          {f.note && <span className="text-ink-3">({f.note})</span>}
                          {f.affected_trade_lines.length > 0 && (
                            <span className="text-ink-2">
                              {" "}
                              · affected Trade Lines:{" "}
                              {f.affected_trade_lines
                                .map((l) => `${l.side} ${l.symbol} ${l.pct_of_portfolio.toFixed(1)}%`)
                                .join(", ")}
                            </span>
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
            <h3 className="mb-1 font-semibold">Client Restrictions</h3>
            {item.restrictions.length === 0 ? (
              <p className="text-ink-2">None.</p>
            ) : (
              <p className="flex flex-wrap gap-1">
                {item.restrictions.map((x) => (
                  <Pill key={`${x.kind}-${x.value}`} tone="neg">
                    {x.kind}: {x.value}
                  </Pill>
                ))}
              </p>
            )}
          </div>
        </div>
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
  const steps = (["compliance", "committee"] as const).filter((s) =>
    s === "compliance" ? canCompliance : canCommittee,
  );
  const [picked, setPicked] = useState<Step | null>(null);
  // The selected item points the Assistant at one Recommendation; the server lists what this role's panel lists.
  const [selected, setSelected] = useState<number | null>(null);
  const liveSelection = q.data?.items.some((i) => i.recommendation.id === selected) ? selected : null;
  usePublishScreen(
    { kind: "approvals", entity_ids: {}, selected_item: liveSelection === null ? null : String(liveSelection) },
    liveSelection === null ? "Approvals" : `Approvals, Recommendation ${liveSelection}`,
  );
  if (q.isError) return <ErrorLine>{q.error.message}</ErrorLine>;
  const items = q.data?.items ?? [];
  const active: Step | undefined = picked && steps.includes(picked) ? picked : steps[0];
  const mine = items.filter((i) => i.step === active);
  return (
    <div className="space-y-3">
      <PageHeader
        title="Pending approvals"
        sub={active ? BLURB[active] : "You can view approvals but not act on them."}
        actions={
          steps.length > 1 ? (
            <div className="seg" role="group" aria-label="Approval queue">
              {steps.map((s) => (
                <button key={s} type="button" aria-pressed={active === s} onClick={() => setPicked(s)}>
                  {TITLE[s]} ({items.filter((i) => i.step === s).length})
                </button>
              ))}
            </div>
          ) : undefined
        }
      />
      {active && (
        <section aria-label={TITLE[active]} className="space-y-2">
          <h2>
            {TITLE[active]} ({mine.length})
          </h2>
          {mine.length === 0 ? (
            <Empty>Nothing is waiting.</Empty>
          ) : (
            <ul className="space-y-3">
              {mine.map((i) => (
                <ItemCard
                  key={i.recommendation.id}
                  item={i}
                  canCompliance={canCompliance}
                  canCommittee={canCommittee}
                  selected={liveSelection === i.recommendation.id}
                  onSelect={() => setSelected(liveSelection === i.recommendation.id ? null : i.recommendation.id)}
                />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
