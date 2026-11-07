/** Report detail: a Report's metadata and every Insight in the review layout, each beside the full text of its cited
 * page with the passage highlighted. An Insight awaiting review offers Approve and Reject at the top of the detail pane;
 * once the server confirms, the selection advances to the next Insight awaiting review in this Report. A failed
 * extraction offers Upload again. Selection, status filter and the page being read all live in the URL, so a reload or a
 * shared link restores them. */
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import {
  KIND_LABEL,
  Outcome,
  STATUS,
  SeedBadge,
  insightCounts,
  reportsPath,
  pageOrder,
  useReports,
  useUrlParams,
  type Insight,
  type InsightStatus,
  type Report,
} from "./research";
import {
  ChevronLeft,
  InsightDetail,
  InsightRow,
  PageReader,
  ReviewNotice,
  SPLIT,
  SplitSkeleton,
  pagesLabel,
  useReviewFlow,
  wholeNumber,
} from "./ReviewLayout";
import { Empty, ErrorLine, Icon, PageHeader, Panel, minuteUtc } from "./ui";
import { UploadReportButton } from "./UploadReportDialog";

type Filter = InsightStatus | "all";
const FILTERS: { value: Filter; text: string }[] = [
  { value: "pending", text: STATUS.pending.text },
  { value: "approved", text: STATUS.approved.text },
  { value: "rejected", text: STATUS.rejected.text },
  { value: "all", text: "All" },
];
const EMPTY_FILTER: Record<InsightStatus, string> = {
  pending: "No Insights in this Report are awaiting review.",
  approved: "No Insights in this Report have been approved.",
  rejected: "No Insights in this Report have been rejected.",
};

function BackLink() {
  return (
    <Link to={reportsPath} className="btn btn-ghost btn-sm mb-1 !pl-1.5">
      <ChevronLeft />
      Reports
    </Link>
  );
}

function ReportHeader({ report }: { report: Report }) {
  return (
    <PageHeader
      title={report.title}
      sub={
        <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="mono text-ink-3">{report.id}</span>
          <span>{KIND_LABEL[report.kind]}</span>
          <span>
            <span className="mono">{report.page_count}</span> {pagesLabel(report.page_count)}
          </span>
          <span>
            Uploaded by <span className="mono text-ink">{report.uploaded_by}</span>
          </span>
          <span title={report.uploaded_at}>
            <span className="mono text-ink">{minuteUtc(report.uploaded_at)}</span> UTC
          </span>
          <Outcome report={report} />
          {report.human_verified && <SeedBadge what="Report" />}
        </span>
      }
    />
  );
}

function InsightList({
  report,
  insights,
  filter,
  selectedId,
  onFilter,
  onSelect,
}: {
  report: Report;
  insights: Insight[];
  filter: Filter;
  selectedId: number | null;
  onFilter: (f: Filter) => void;
  onSelect: (id: number) => void;
}) {
  const counts = insightCounts(report);
  const total = report.insights.length;
  return (
    <Panel
      title="Insights"
      label="Insights"
      aside={
        <>
          <span className="mono">{total}</span> in page order
        </>
      }
    >
      <div role="group" aria-label="Filter Insights by status" className="seg mb-3 flex-wrap">
        {FILTERS.map((f) => (
          <button key={f.value} type="button" aria-pressed={filter === f.value} onClick={() => onFilter(f.value)}>
            {f.text} <span className="mono text-ink-3">{f.value === "all" ? total : counts[f.value]}</span>
          </button>
        ))}
      </div>
      {insights.length === 0 ? (
        <Empty>{filter === "all" ? "This Report has no Insights." : EMPTY_FILTER[filter]}</Empty>
      ) : (
        <ul className="-mx-1 flex flex-col gap-1">
          {insights.map((i) => (
            <InsightRow key={i.id} insight={i} selected={i.id === selectedId} onSelect={() => onSelect(i.id)} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ReportDetail({ report, canUpload, canReview }: { report: Report; canUpload: boolean; canReview: boolean }) {
  const [params, update] = useUrlParams();
  const rawFilter = params.get("status");
  const filter: Filter = FILTERS.some((f) => f.value === rawFilter) ? (rawFilter as Filter) : "all";
  const insightParam = params.get("insight");
  const pageParam = wholeNumber(params.get("page"));

  const ordered = useMemo(() => [...report.insights].sort(pageOrder), [report.insights]);
  const shown = useMemo(
    () => (filter === "all" ? ordered : ordered.filter((i) => i.status === filter)),
    [ordered, filter],
  );
  // No Insight in the URL means the first one shown; an Insight in the URL stays selected even when filtered out.
  const selected =
    insightParam === null ? (shown[0] ?? null) : (ordered.find((i) => i.id === wholeNumber(insightParam)) ?? null);
  const unknownInsight = insightParam !== null && selected === null;
  const page =
    pageParam !== null && pageParam >= 1 && pageParam <= report.page_count ? pageParam : (selected?.page ?? 1);

  // When none remain the selection stays on the Insight just reviewed, now read-only.
  const { notice, clearNotice, detailRef, reviewFor } = useReviewFlow({
    order: ordered,
    selected,
    canReview,
    onAdvance: (from, next) => update({ insight: String((next ?? from).id), page: null }),
  });

  const counts = insightCounts(report);
  const fullyReviewed = canReview && report.insights.length > 0 && counts.pending === 0;

  const failed = report.extraction_status === "failed";
  return (
    <div>
      <BackLink />
      <ReportHeader report={report} />
      {failed && (
        <div className="mb-3 space-y-2">
          <ErrorLine>
            Extraction failed: {report.extraction_error ?? "no error was recorded"}. No Insights were kept from this
            Report.
          </ErrorLine>
          {canUpload && <UploadReportButton className="btn btn-primary btn-sm">Upload again</UploadReportButton>}
        </div>
      )}
      <div className={SPLIT}>
        {report.insights.length === 0 ? (
          <Panel title="Insights" label="Insights">
            <Empty>
              {failed ? "No Insights, because extraction failed." : "No Insights were extracted from this Report."} Its{" "}
              <span className="mono">{report.page_count}</span> {pagesLabel(report.page_count)} can still be read.
            </Empty>
          </Panel>
        ) : (
          <InsightList
            report={report}
            insights={shown}
            filter={filter}
            selectedId={selected?.id ?? null}
            // A page read for the old selection would outlive it when the filter moves the default selection.
            onFilter={(f) => update({ status: f === "all" ? null : f, page: null })}
            onSelect={(id) => {
              clearNotice();
              update({ insight: String(id), page: null });
            }}
          />
        )}
        <div className="min-w-0 space-y-3">
          <ReviewNotice notice={notice} onDismiss={clearNotice} />
          {fullyReviewed && (
            <p className="callout callout-pos">
              <Icon name="approvals" size={14} />
              This Report is fully reviewed: none of its <span className="mono">{report.insights.length}</span> Insights
              are awaiting review.
            </p>
          )}
          {unknownInsight && (
            <Panel label="Insight not found">
              <Empty>
                Insight <span className="mono">#{insightParam}</span> is not in this Report. The link may be wrong.
              </Empty>
              {ordered.length > 0 && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => update({ insight: null, page: null, status: null })}
                >
                  Show the first Insight
                </button>
              )}
            </Panel>
          )}
          {selected && <InsightDetail ref={detailRef} insight={selected} review={reviewFor(selected)} />}
          {report.page_count > 0 && (
            <PageReader
              report={report}
              page={page}
              cited={selected}
              onPage={(p) => update({ page: selected && p === selected.page ? null : String(p) })}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div aria-busy>
      <p role="status" className="sr-only">
        Loading Report…
      </p>
      <BackLink />
      <div className="mb-4 space-y-2" aria-hidden>
        <span className="skeleton !h-7" style={{ width: "40%" }} />
        <span className="skeleton" style={{ width: "55%" }} />
      </div>
      <SplitSkeleton listTitle="Insights" />
    </div>
  );
}

/** Route element for /research/reports/:reportId. `canUpload`: a failed extraction offers Upload again. `canReview`:
 * Insights awaiting review offer Approve and Reject. */
export function ReportDetailPage({ canUpload, canReview }: { canUpload: boolean; canReview: boolean }) {
  const { reportId = "" } = useParams();
  const reports = useReports();

  if (reports.isError)
    return (
      <div>
        <BackLink />
        <ErrorLine>{reports.error.message}. Reload the page to try again.</ErrorLine>
      </div>
    );
  if (!reports.data) return <DetailSkeleton />;
  const report = reports.data.items.find((r) => r.id === reportId);
  if (!report)
    return (
      <div>
        <BackLink />
        <PageHeader title="Report not found" />
        <Panel label="Report not found">
          <Empty>
            There is no Report <span className="mono">{reportId}</span>. The link may be wrong; every Report is listed
            under Reports.
          </Empty>
        </Panel>
      </div>
    );
  return <ReportDetail report={report} canUpload={canUpload} canReview={canReview} />;
}
