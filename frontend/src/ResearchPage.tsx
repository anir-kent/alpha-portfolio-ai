import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { Empty, ErrorLine, Icon, PageHeader, Panel, Pill, minuteUtc, type Tone } from "./ui";

type Report = components["schemas"]["ReportOut"];
type InsightStatus = components["schemas"]["InsightOut"]["status"];
export type InsightCounts = Record<InsightStatus, number>;

const KIND_LABEL: Record<Report["kind"], string> = { pdf: "PDF", text: "Text" };
const OUTCOME: Record<Report["extraction_status"], { tone: Tone; text: string; hint: string }> = {
  complete: { tone: "pos", text: "Extracted", hint: "Insights were extracted by the LLM and await an Insight Review" },
  seeded: { tone: "mute", text: "Seeded", hint: "Insights were loaded from a human-verified seed, not extracted" },
  failed: { tone: "neg", text: "Extraction failed", hint: "No Insights could be extracted" },
};
const SKELETON_ROWS = 4;
const COLUMNS: { label: string; num?: boolean }[] = [
  { label: "Report" },
  { label: "Kind" },
  { label: "Pages", num: true },
  { label: "Uploaded by" },
  { label: "Uploaded (UTC)" },
  { label: "Extraction" },
  { label: "Awaiting review", num: true },
  { label: "Approved", num: true },
  { label: "Rejected", num: true },
];

/** The Report list, every Report with all its Insights in every status. The To review tab (ticket 05) builds on the same query. */
export function useReports() {
  return useQuery({
    queryKey: ["reports"],
    queryFn: async () => {
      // A network failure throws rather than returning an error; both read the same to the Analyst.
      const res = await api.GET("/api/reports").catch(() => null);
      if (!res?.data) throw new Error("Could not load Reports");
      return res.data;
    },
  });
}

/** Insight counts by status, derived from the Report itself so every view that shows them agrees. */
export function insightCounts(report: Report): InsightCounts {
  const counts: InsightCounts = { pending: 0, approved: 0, rejected: 0 };
  for (const insight of report.insights) counts[insight.status] += 1;
  return counts;
}

/** Newest upload first; ties broken by id so the order is stable across refetches. */
const newestFirst = (a: Report, b: Report) => b.uploaded_at.localeCompare(a.uploaded_at) || a.id.localeCompare(b.id);

function Outcome({ report }: { report: Report }) {
  const outcome = OUTCOME[report.extraction_status];
  return (
    <Pill tone={outcome.tone} title={report.extraction_error ?? outcome.hint}>
      {report.extraction_status === "failed" && <Icon name="alert" size={10} />}
      {outcome.text}
    </Pill>
  );
}

function ReportRow({ report }: { report: Report }) {
  const counts = insightCounts(report);
  const failed = report.extraction_status === "failed";
  return (
    <tr
      className={failed ? "!bg-neg-bg" : undefined}
      style={{ boxShadow: failed ? "inset 3px 0 var(--color-neg)" : undefined }}
    >
      <td className="min-w-[18rem]">
        <div className="flex flex-col items-start gap-1">
          <span className="font-semibold">{report.title}</span>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="mono text-ink-3">{report.id}</span>
            {report.human_verified && (
              <Pill tone="ai" title="Insights were verified by a person when seeded, not extracted by the LLM">
                <Icon name="approvals" size={10} />
                Human-verified seed
              </Pill>
            )}
          </span>
        </div>
      </td>
      <td>{KIND_LABEL[report.kind]}</td>
      <td className="num">{report.page_count}</td>
      <td className="mono">{report.uploaded_by}</td>
      <td className="mono whitespace-nowrap" title={report.uploaded_at}>
        {minuteUtc(report.uploaded_at)}
      </td>
      <td>
        <Outcome report={report} />
      </td>
      <td className={`num ${counts.pending > 0 ? "font-semibold text-info" : "text-ink-3"}`}>{counts.pending}</td>
      <td className="num">{counts.approved}</td>
      <td className="num">{counts.rejected}</td>
    </tr>
  );
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: SKELETON_ROWS }, (_, i) => (
        <tr key={i} aria-hidden>
          {COLUMNS.map((c, j) => (
            <td key={c.label}>
              <span className="skeleton" style={{ width: j === 0 ? "70%" : "60%" }} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function ReportsTab() {
  const reports = useReports();
  const rows = useMemo(() => [...(reports.data?.items ?? [])].sort(newestFirst), [reports.data]);

  if (reports.isError) return <ErrorLine>{reports.error.message}. Reload the page to try again.</ErrorLine>;
  if (reports.data && rows.length === 0)
    return (
      <Panel title="Reports" label="Reports">
        <Empty>No Reports yet. Uploaded and seeded Reports appear here with their Insights.</Empty>
      </Panel>
    );
  return (
    <Panel
      title="Reports"
      label="Reports"
      aside={
        reports.data && (
          <>
            <span className="mono">{rows.length}</span> {rows.length === 1 ? "Report" : "Reports"}, newest first
          </>
        )
      }
      flush
    >
      {reports.isLoading && (
        <p role="status" className="sr-only">
          Loading Reports…
        </p>
      )}
      <table className="grid-table">
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th key={c.label} className={c.num ? "num" : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{reports.isLoading ? <SkeletonRows /> : rows.map((r) => <ReportRow key={r.id} report={r} />)}</tbody>
      </table>
    </Panel>
  );
}

/** The Research screen. Opens on Reports; the To review tab arrives with the Insight inbox. */
export function ResearchPage() {
  return (
    <div>
      <PageHeader
        title="Research"
        sub="Reports in the platform and the Insights extracted from them. No Insight informs a Portfolio until it is approved."
      />
      <div role="tablist" aria-label="Research sections" className="seg mb-3">
        <button type="button" role="tab" aria-selected id="research-tab-reports" aria-controls="research-panel-reports">
          Reports
        </button>
      </div>
      <div role="tabpanel" id="research-panel-reports" aria-labelledby="research-tab-reports">
        <ReportsTab />
      </div>
    </div>
  );
}
