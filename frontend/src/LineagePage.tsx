import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";

type Node = components["schemas"]["LineageNode"];

const STAGES: Record<Node["stage"], string> = {
  report: "Report", insight: "Insight", research_tilt: "Research Tilt", recommendation: "Recommendation",
  decision: "Decision", analysis: "Analysis run",
};

function NodeCard({ n }: { n: Node }) {
  const ai = n.actor.model != null;
  return (
    <li
      className={`rounded border p-3 ${n.override ? "border-amber-500 bg-amber-50" : "border-slate-200"}`}
      aria-label={`${STAGES[n.stage]}: ${n.type}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-slate-500">{STAGES[n.stage]}</span>
        <span className="font-medium">{n.type.replace(/_/g, " ")}</span>
        <span className="text-xs text-slate-500">#{n.id}</span>
        {n.override && <span className="rounded bg-amber-500 px-2 py-0.5 text-xs font-semibold text-white">Override</span>}
        {n.human_verified && <span className="rounded bg-green-700 px-2 py-0.5 text-xs font-semibold text-white">Human-verified</span>}
      </div>
      <p className="mt-1 text-sm">
        {n.actor.name}
        {n.actor.role && <span className="text-slate-500"> ({n.actor.role})</span>}
        <span className="text-slate-500"> · {n.timestamp}</span>
        {ai && <span className="block text-slate-600">AI event: {n.actor.model} · prompt {n.actor.prompt_version}</span>}
      </p>
      {n.source && (
        <blockquote className="mt-2 border-l-4 border-slate-300 pl-3 text-sm italic text-slate-700">
          “{n.source.passage}”
          <footer className="not-italic text-xs text-slate-500">{n.source.report_title ?? n.source.report_id}, page {n.source.page}</footer>
        </blockquote>
      )}
      {typeof n.payload.rationale === "string" && <p className="mt-1 text-sm">Rationale: {n.payload.rationale}</p>}
      <p className="mt-1 text-xs text-slate-500">Derived from: {n.parent_ids.length ? n.parent_ids.map((p) => `#${p}`).join(", ") : "—"}</p>
    </li>
  );
}

export function LineagePage() {
  const { id } = useParams();
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
      <p className="mb-2 text-sm"><Link className="underline" to="/audit">← Audit</Link></p>
      <h1 className="mb-1 text-xl font-semibold">Lineage of Recommendation #{id}</h1>
      <p className="mb-4 text-sm text-slate-600">Oldest first, from the Report passage to the final Decision.</p>
      {lineage.isError && <p className="text-red-600">{lineage.error.message}</p>}
      {lineage.data && <ol className="space-y-2">{lineage.data.nodes.map((n) => <NodeCard key={n.id} n={n} />)}</ol>}
    </div>
  );
}
