import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  KIND_LABEL,
  Outcome,
  SeedBadge,
  toReviewGroups,
  toReviewPath,
  insightCounts,
  reportsPath,
  newestFirst,
  reportPath,
  useReports,
  type Report,
} from "./research";
import { ToReviewTab } from "./ToReview";
import { Empty, ErrorLine, Icon, PageHeader, Panel, minuteUtc } from "./ui";
import { UploadReportButton } from "./UploadReportDialog";

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

function ReportRow({ report }: { report: Report }) {
  const navigate = useNavigate();
  const counts = insightCounts(report);
  const failed = report.extraction_status === "failed";
  return (
    // The whole row opens the Report for the mouse; the title link is the keyboard and screen-reader path.
    <tr
      className={`cursor-pointer ${failed ? "!bg-neg-bg" : ""}`}
      style={{ boxShadow: failed ? "inset 3px 0 var(--color-neg)" : undefined }}
      onClick={() => navigate(reportPath(report.id))}
    >
      <td className="min-w-[18rem]">
        <div className="flex flex-col items-start gap-1">
          <Link
            to={reportPath(report.id)}
            className="font-semibold hover:text-info hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {report.title}
          </Link>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="mono text-ink-3">{report.id}</span>
            {report.human_verified && <SeedBadge what="Report" />}
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

export type ResearchTab = "to-review" | "reports";
const TABS: { value: ResearchTab; text: string; path: string }[] = [
  { value: "to-review", text: "To review", path: toReviewPath },
  { value: "reports", text: "Reports", path: reportsPath },
];

/** The number awaiting review on the To review tab, from the same inbox groups the tab lists. Hidden while loading. */
function AwaitingBadge() {
  const reports = useReports();
  if (!reports.data) return null;
  const total = toReviewGroups(reports.data.items).reduce((n, g) => n + g.insights.length, 0);
  return (
    <>
      <span className="tab-count" data-zero={total === 0} aria-hidden>
        {total}
      </span>
      <span className="sr-only">, {total} awaiting review</span>
    </>
  );
}

/** The Research screen: To review (where it opens) and the Reports library, each with its own URL. `canUpload`: the
 * session holds `report:upload`, so the header offers Upload Report. `canReview`: it holds `insight:approve`. */
export function ResearchPage({
  tab,
  canUpload,
  canReview,
}: {
  tab: ResearchTab;
  canUpload: boolean;
  canReview: boolean;
}) {
  return (
    <div>
      <PageHeader
        title="Research"
        sub="Reports in the platform and the Insights extracted from them. No Insight informs a Portfolio until it is approved."
        actions={
          canUpload && (
            <UploadReportButton className="btn btn-primary">
              <Icon name="research" />
              Upload Report
            </UploadReportButton>
          )
        }
      />
      <nav aria-label="Research sections" className="seg mb-3">
        {TABS.map((t) => (
          <Link key={t.value} to={t.path} aria-current={tab === t.value ? "page" : undefined}>
            {t.text}
            {t.value === "to-review" && <AwaitingBadge />}
          </Link>
        ))}
      </nav>
      {tab === "to-review" ? <ToReviewTab canReview={canReview} canUpload={canUpload} /> : <ReportsTab />}
    </div>
  );
}
