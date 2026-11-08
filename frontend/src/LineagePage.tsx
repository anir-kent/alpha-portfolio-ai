import { useQuery } from "@tanstack/react-query";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "./api/client";
import { ExchangeDrawer } from "./ExchangeDrawer";
import type { components } from "./api/schema";
import { ErrorLine, Icon, PageHeader, Panel, Pill, Empty } from "./ui";

type Node = components["schemas"]["LineageNode"];
type Stage = Node["stage"];

const STAGES: Record<Stage, string> = {
  analysis: "Analysis run",
  report: "Report passage",
  insight: "Insight",
  research_tilt: "Research Tilt",
  recommendation: "Recommendation",
  decision: "Decisions",
};
/** Columns left to right: Report passage → Insight → Tilt → Recommendation → Decisions (analysis runs share the first). */
const COLUMNS: Stage[][] = [["analysis", "report"], ["insight"], ["research_tilt"], ["recommendation"], ["decision"]];
const COLUMN_TITLE = ["Report passage", "Insight", "Research Tilt", "Recommendation", "Decisions"];

/** The final Exchange of the LLM Trajectory an AI node's event anchors, if the event was captured (pre-capture events
 * carry none). Events written before Trajectories carry a single `exchange_id` instead of an `exchanges` list. */
export function exchangeIdOf(n: Node): number | null {
  const anchored = n.payload.exchanges;
  const last: unknown = Array.isArray(anchored) ? anchored[anchored.length - 1] : undefined;
  const id = last && typeof last === "object" && "exchange_id" in last ? last.exchange_id : n.payload.exchange_id;
  return typeof id === "number" ? id : null;
}

/** An Insight's extraction folds into the card of the Insight Review that decided it, so the Insight column shows one card per
 * Insight instead of two. `folded`: extraction id -> its review; `extractionOf`: review id -> its extraction. */
function foldExtractions(nodes: Node[]): { folded: Map<number, Node>; extractionOf: Map<number, Node> } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const folded = new Map<number, Node>();
  const extractionOf = new Map<number, Node>();
  for (const n of nodes) {
    if (n.type !== "insight_approved" && n.type !== "insight_rejected") continue;
    for (const p of n.parent_ids) {
      const parent = byId.get(p);
      if (parent?.type !== "insight_extracted") continue;
      folded.set(p, n);
      extractionOf.set(n.id, parent);
    }
  }
  return { folded, extractionOf };
}

function NodeCard({
  n,
  refCb,
  onView,
  extraction,
}: {
  n: Node;
  refCb: (el: HTMLLIElement | null) => void;
  onView?: (id: number) => void;
  extraction?: Node;
}) {
  const ai = n.actor.model != null;
  const exchangeId = exchangeIdOf(n);
  return (
    <li
      ref={refCb}
      className={`panel relative z-10 p-2 ${n.override ? "!border-[#d99a2b] !bg-warn-bg" : ""}`}
      aria-label={`${STAGES[n.stage]}: ${n.type}`}
    >
      <div className="flex flex-wrap items-center gap-1">
        <span className="font-semibold">{n.type.replace(/_/g, " ")}</span>
        <span className="mono ml-auto text-ink-3">#{n.id}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-1">
        {n.override && <Pill tone="warn">Override</Pill>}
        {n.human_verified && (
          <Pill tone="pos">
            <Icon name="approvals" size={10} />
            Human-verified
          </Pill>
        )}
        {ai && (
          <Pill tone="ai">
            <Icon name="spark" size={10} />
            AI
          </Pill>
        )}
      </div>
      <p className="mt-0.5 text-ink-2">
        {n.actor.name}
        {n.actor.role && <span className="text-ink-3"> ({n.actor.role})</span>}
      </p>
      <p className="mono text-[0.7692rem] text-ink-3">{n.timestamp}</p>
      {ai && (
        <p className="mono text-[0.7692rem] text-ai">
          {n.actor.model} · {n.actor.prompt_version}
        </p>
      )}
      {ai && onView && exchangeId !== null && (
        <button type="button" className="btn btn-sm mt-1" onClick={() => onView(exchangeId)}>
          View LLM Exchange
        </button>
      )}
      {n.source && (
        <blockquote className="mt-1 border-l-[3px] border-line-strong pl-2 text-ink-2 italic">
          &ldquo;{n.source.passage}&rdquo;
          <footer className="text-[0.7692rem] text-ink-3 not-italic">
            {n.source.report_title ?? n.source.report_id}, page {n.source.page}
          </footer>
        </blockquote>
      )}
      {typeof n.payload.rationale === "string" && <p className="mt-1">Rationale: {n.payload.rationale}</p>}
      {extraction && (
        <p className="mt-1 text-[0.7692rem] text-ink-3">
          Extracted <span className="mono">#{extraction.id}</span> by {extraction.actor.name}
          {extraction.actor.model && <span className="mono text-ai"> · {extraction.actor.model}</span>} at{" "}
          <span className="mono">{extraction.timestamp}</span>
        </p>
      )}
      <p className="mt-1 text-[0.7692rem] text-ink-3">
        Derived from: {n.parent_ids.length ? n.parent_ids.map((p) => `#${p}`).join(", ") : "—"}
      </p>
    </li>
  );
}

/** Lineage DAG: nodes sit in stage columns, SVG curves follow each parent link measured from the rendered cards. */
function Dag({ nodes, onView }: { nodes: Node[]; onView?: (id: number) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const els = useRef(new Map<number, HTMLLIElement>());
  const [edges, setEdges] = useState<{ d: string; key: string; override: boolean }[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });

  const { folded, extractionOf } = useMemo(() => foldExtractions(nodes), [nodes]);

  useLayoutEffect(() => {
    // A link to or from a folded extraction is drawn to or from the review card it folded into.
    const cardOf = (id: number) => folded.get(id)?.id ?? id;
    const measure = () => {
      const box = wrap.current?.getBoundingClientRect();
      if (!box) return;
      const next: typeof edges = [];
      for (const n of nodes) {
        if (folded.has(n.id)) continue;
        const to = els.current.get(n.id)?.getBoundingClientRect();
        if (!to) continue;
        for (const parent of n.parent_ids) {
          const p = cardOf(parent);
          if (p === n.id) continue; // the folded extraction itself
          const from = els.current.get(p)?.getBoundingClientRect();
          if (!from) continue;
          const x1 = from.right - box.left,
            y1 = from.top + from.height / 2 - box.top;
          const x2 = to.left - box.left,
            y2 = to.top + to.height / 2 - box.top;
          const mx = Math.max(12, Math.abs(x2 - x1) / 2);
          next.push({
            key: `${p}-${n.id}`,
            override: n.override,
            d: `M${x1},${y1} C${x1 + mx},${y1} ${x2 - mx},${y2} ${x2},${y2}`,
          });
        }
      }
      setEdges(next);
      setSize({ w: box.width, h: box.height });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [nodes, folded]);

  return (
    <div ref={wrap} className="relative overflow-x-auto">
      <svg className="pointer-events-none absolute left-0 top-0" width={size.w} height={size.h} aria-hidden="true">
        {edges.map((e) => (
          <path key={e.key} d={e.d} fill="none" stroke={e.override ? "#d99a2b" : "#8a99b3"} strokeWidth="1.5" />
        ))}
      </svg>
      <div className="grid min-w-[62rem] grid-cols-5 gap-x-8">
        {COLUMNS.map((stages, i) => {
          const col = nodes.filter((n) => stages.includes(n.stage) && !folded.has(n.id));
          return (
            <div key={COLUMN_TITLE[i]}>
              <p className="eyebrow mb-1.5">{COLUMN_TITLE[i]}</p>
              <ol className="space-y-2">
                {col.map((n) => (
                  <NodeCard
                    key={n.id}
                    n={n}
                    onView={onView}
                    extraction={extractionOf.get(n.id)}
                    refCb={(el) => {
                      if (el) els.current.set(n.id, el);
                      else els.current.delete(n.id);
                    }}
                  />
                ))}
                {col.length === 0 && (
                  <li className="rounded-xl border border-dashed border-line-strong p-2 text-ink-3">none</li>
                )}
              </ol>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function LineagePage({ canViewExchange = false }: { canViewExchange?: boolean }) {
  const { id } = useParams();
  const [exchangeId, setExchangeId] = useState<number | null>(null);
  const lineage = useQuery({
    queryKey: ["lineage", id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/recommendations/{recommendation_id}/lineage", {
        params: { path: { recommendation_id: Number(id) } },
      });
      if (error || !data) throw new Error("Lineage could not be loaded");
      return data;
    },
  });
  return (
    <div>
      <PageHeader
        title={
          <>
            Lineage of Recommendation <span className="mono">#{id}</span>
          </>
        }
        sub={
          <>
            <Link className="text-brand hover:underline" to="/audit">
              ← Audit
            </Link>{" "}
            · Oldest first, from the Report passage to the final Decision. Amber marks a human override.
          </>
        }
      />
      {lineage.isError && <ErrorLine>{lineage.error.message}</ErrorLine>}
      {lineage.data && (
        <Panel label="Lineage graph">
          {lineage.data.nodes.length === 0 ? (
            <Empty>No audit events for this Recommendation.</Empty>
          ) : (
            <Dag nodes={lineage.data.nodes} onView={canViewExchange ? setExchangeId : undefined} />
          )}
        </Panel>
      )}
      {exchangeId !== null && (
        <ExchangeDrawer id={exchangeId} canLineage onClose={() => setExchangeId(null)} onNavigate={setExchangeId} />
      )}
    </div>
  );
}
