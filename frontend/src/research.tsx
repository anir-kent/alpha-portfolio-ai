/** Data and vocabulary shared by the Research screens: the Report list query, Insight counts and the pills that label
 * Reports and Insights the same way everywhere. */
import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { Icon, Pill, type Tone } from "./ui";

export type Report = components["schemas"]["ReportOut"];
export type ReportList = components["schemas"]["ReportList"];
export type Insight = components["schemas"]["InsightOut"];
export type InsightStatus = Insight["status"];
export type InsightCounts = Record<InsightStatus, number>;

export const KIND_LABEL: Record<Report["kind"], string> = { pdf: "PDF", text: "Text" };
const OUTCOME: Record<Report["extraction_status"], { tone: Tone; text: string; hint: string }> = {
  complete: { tone: "pos", text: "Extracted", hint: "Insights were extracted by the LLM and await an Insight Review" },
  seeded: { tone: "mute", text: "Seeded", hint: "Insights were loaded from a human-verified seed, not extracted" },
  failed: { tone: "neg", text: "Extraction failed", hint: "No Insights could be extracted" },
};
export const STATUS: Record<InsightStatus, { tone: Tone; text: string }> = {
  pending: { tone: "info", text: "Awaiting review" },
  approved: { tone: "pos", text: "Approved" },
  rejected: { tone: "neg", text: "Rejected" },
};
export const SUBJECT_KIND: Record<Insight["subject_kind"], string> = { sector: "Sector", asset_class: "Asset Class" };
export const DIRECTION: Record<Insight["direction"], { tone: Tone; text: string }> = {
  positive: { tone: "pos", text: "Positive" },
  neutral: { tone: "mute", text: "Neutral" },
  negative: { tone: "neg", text: "Negative" },
};
export const CONFIDENCE: Record<Insight["confidence"], { tone: Tone; text: string }> = {
  high: { tone: "info", text: "High confidence" },
  medium: { tone: "mute", text: "Medium confidence" },
  low: { tone: "warn", text: "Low confidence" },
};

/** The Report list, every Report with all its Insights in every status. Report detail and the To review tab read the
 * same query, so counts agree across views and one cache update after an Insight Review moves them all. */
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

/** One page of a Report's text. Page text never changes once stored, so each page is fetched once and kept. */
export function useReportPage(reportId: string, page: number) {
  return useQuery({
    queryKey: ["report-page", reportId, page],
    staleTime: Infinity,
    retry: 1,
    queryFn: async () => {
      const res = await api
        .GET("/api/reports/{report_id}/pages/{page}", { params: { path: { report_id: reportId, page } } })
        .catch(() => null);
      if (!res?.data) throw new Error(`Could not load page ${page}`);
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

/** The detail URL for a Report; the library, the To review tab and the upload dialog all link to it. */
export const reportPath = (id: string) => `/research/reports/${encodeURIComponent(id)}`;

/** Page order, then ID: the order the document was written in, stable across refetches. */
export const pageOrder = (a: Insight, b: Insight) => a.page - b.page || a.id - b.id;

export function Outcome({ report }: { report: Report }) {
  const outcome = OUTCOME[report.extraction_status];
  return (
    <Pill tone={outcome.tone} title={report.extraction_error ?? outcome.hint}>
      {report.extraction_status === "failed" && <Icon name="alert" size={10} />}
      {outcome.text}
    </Pill>
  );
}

export function SeedBadge({ what }: { what: "Report" | "Insight" }) {
  return (
    <Pill
      tone="ai"
      title={
        what === "Report"
          ? "Insights were verified by a person when seeded, not extracted by the LLM"
          : "This Insight was verified by a person when seeded, not extracted by the LLM"
      }
    >
      <Icon name="approvals" size={10} />
      Human-verified seed
    </Pill>
  );
}
