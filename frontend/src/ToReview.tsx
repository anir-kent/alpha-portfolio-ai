/** To review: the Research Analyst's inbox. Every Insight awaiting review across all Reports, grouped by Report (newest
 * upload first, Insights in page order), built from the Report list with no call of its own. Selecting an Insight shows
 * the same review layout and actions as Report detail; after an Insight Review the selection advances through the inbox
 * across Report boundaries, and an empty inbox says "All caught up". The selection and the page being read live in the
 * URL. */
import { useMemo, type Ref } from "react";
import { Link } from "react-router-dom";
import {
  isAwaitingReview,
  toReviewGroups,
  reportsPath,
  reportPath,
  useReports,
  useUrlParams,
  type ToReviewGroup,
  type Report,
} from "./research";
import {
  InsightDetail,
  InsightRow,
  InsightStepper,
  PageReader,
  ReviewNotice,
  SplitSkeleton,
  SPLIT,
  useInsightStepper,
  type InsightStepperState,
  useReviewFlow,
  wholeNumber,
} from "./ReviewLayout";
import { Empty, ErrorLine, Icon, Panel, Pill, minuteUtc } from "./ui";
import { UploadReportButton } from "./UploadReportDialog";

const awaitingLabel = (n: number) => `${n} ${n === 1 ? "Insight" : "Insights"} awaiting review`;

function GroupHeader({ report, remaining, id }: { report: Report; remaining: number; id: string }) {
  return (
    <div className="inbox-group-head">
      <div className="flex items-start gap-2">
        <h3 id={id} className="min-w-0 flex-1 !text-[1rem] !font-semibold">
          <Link to={reportPath(report.id)} className="hover:text-info hover:underline">
            {report.title}
          </Link>
        </h3>
        <Pill tone="info" title={awaitingLabel(remaining)}>
          <span className="mono">{remaining}</span> to review
        </Pill>
      </div>
      <p className="flex flex-wrap gap-x-3 text-ink-3">
        <span>
          Uploaded by <span className="mono text-ink-2">{report.uploaded_by}</span>
        </span>
        <span title={report.uploaded_at}>
          <span className="mono text-ink-2">{minuteUtc(report.uploaded_at)}</span> UTC
        </span>
      </p>
    </div>
  );
}

function InboxList({
  groups,
  total,
  selectedId,
  onSelect,
  stepper,
}: {
  groups: ToReviewGroup[];
  total: number;
  selectedId: number | null;
  onSelect: (id: number) => void;
  stepper: InsightStepperState;
}) {
  return (
    <Panel
      title="To review"
      label="Insights awaiting review"
      aside={
        <>
          <span className="mono">{total}</span> in <span className="mono">{groups.length}</span>{" "}
          {groups.length === 1 ? "Report" : "Reports"}, newest first
        </>
      }
    >
      {groups.length === 0 ? (
        <Empty>Nothing else is awaiting review.</Empty>
      ) : (
        <>
          <InsightStepper stepper={stepper} />
          {groups.map(({ report, insights }) => (
            <section key={report.id} className="inbox-group" aria-labelledby={`inbox-${report.id}`}>
              <GroupHeader report={report} remaining={insights.length} id={`inbox-${report.id}`} />
              <ul className="-mx-1 flex flex-col gap-1">
                {insights.map((i) => (
                  <InsightRow
                    key={i.id}
                    insight={i}
                    selected={i.id === selectedId}
                    onSelect={() => onSelect(i.id)}
                    showStatus={false}
                  />
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </Panel>
  );
}

/** The empty inbox, the normal state on a freshly seeded database. It takes focus after the last Insight Review. */
function CaughtUp({ canUpload, ref }: { canUpload: boolean; ref: Ref<HTMLElement> }) {
  return (
    <section ref={ref} tabIndex={-1} className="panel outline-none" aria-labelledby="caught-up-title">
      <div className="caught-up">
        <span className="caught-up-coin" aria-hidden>
          <Icon name="approvals" size={22} />
        </span>
        <h2 id="caught-up-title" className="!text-[1.2308rem] !font-semibold">
          All caught up
        </h2>
        <p className="max-w-[34rem] text-ink-2">
          No Insights are awaiting review. When a Report is uploaded, the Insights extracted from it appear here.
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-2">
          {canUpload && (
            <UploadReportButton className="btn btn-primary">
              <Icon name="research" />
              Upload Report
            </UploadReportButton>
          )}
          <Link to={reportsPath} className="btn">
            Browse Reports
          </Link>
        </div>
      </div>
    </section>
  );
}

function Inbox({ reports, canReview, canUpload }: { reports: Report[]; canReview: boolean; canUpload: boolean }) {
  const [params, update] = useUrlParams();
  const groups = useMemo(() => toReviewGroups(reports), [reports]);
  const order = useMemo(() => groups.flatMap((g) => g.insights), [groups]);
  const insightParam = params.get("insight");
  const pageParam = wholeNumber(params.get("page"));

  // No Insight in the URL means the first in the inbox. A linked Insight is found in any Report, so a link to one that
  // has since been reviewed still opens it, read-only.
  const linkedId = wholeNumber(insightParam);
  const selected =
    insightParam === null
      ? (order[0] ?? null)
      : (reports.flatMap((r) => r.insights).find((i) => i.id === linkedId) ?? null);
  const report = selected ? (reports.find((r) => r.id === selected.report_id) ?? null) : null;
  const unknownInsight = insightParam !== null && selected === null;
  const page =
    report && pageParam !== null && pageParam >= 1 && pageParam <= report.page_count
      ? pageParam
      : (selected?.page ?? 1);

  // With none left after a saved review the URL drops the Insight, and the inbox shows All caught up. After a 409 the
  // cache still lists the Insight as awaiting review until the refetch lands, so it stays selected and then shows the
  // other Analyst's Insight Review read-only, rather than falling back to it as the first in the inbox.
  const { notice, clearNotice, detailRef, reviewFor } = useReviewFlow({
    order,
    selected,
    canReview,
    onAdvance: (from, next, outcome) =>
      update({ insight: next ? String(next.id) : outcome === "already-reviewed" ? String(from.id) : null, page: null }),
  });
  const select = (id: number) => {
    clearNotice();
    update({ insight: String(id), page: null });
  };
  // j/k and the arrows move through the inbox in its order, across Report groups.
  const stepper = useInsightStepper({ list: order, selectedId: selected?.id ?? null, onSelect: select });
  const showFirst = () => {
    clearNotice();
    update({ insight: null, page: null });
  };

  if (order.length === 0 && selected === null && !unknownInsight)
    return (
      <div className="space-y-3">
        <ReviewNotice notice={notice} onDismiss={clearNotice} />
        <CaughtUp ref={detailRef} canUpload={canUpload} />
      </div>
    );

  return (
    <div className={SPLIT}>
      <InboxList
        groups={groups}
        total={order.length}
        selectedId={selected?.id ?? null}
        onSelect={select}
        stepper={stepper}
      />
      <div className="min-w-0 space-y-3">
        <ReviewNotice notice={notice} onDismiss={clearNotice} />
        {unknownInsight && (
          <Panel label="Insight not found">
            <Empty>
              There is no Insight <span className="mono">#{insightParam}</span>. The link may be wrong.
            </Empty>
            {order.length > 0 && (
              <button type="button" className="btn btn-sm" onClick={showFirst}>
                Show the first Insight awaiting review
              </button>
            )}
          </Panel>
        )}
        {selected && !isAwaitingReview(selected) && (
          <div className="callout callout-info flex-wrap">
            <Icon name="alert" size={14} />
            <span className="flex-1">
              This Insight is no longer awaiting review; its Insight Review is shown below.
            </span>
            {order.length > 0 && (
              <button type="button" className="btn btn-sm" onClick={showFirst}>
                Show the first Insight awaiting review
              </button>
            )}
          </div>
        )}
        {selected && (
          <InsightDetail
            ref={detailRef}
            insight={selected}
            review={reviewFor(selected)}
            context={
              report && (
                <p className="mb-1 text-ink-3">
                  From{" "}
                  <Link to={reportPath(report.id)} className="font-semibold text-ink-2 hover:text-info hover:underline">
                    {report.title}
                  </Link>
                </p>
              )
            }
          />
        )}
        {report && report.page_count > 0 && (
          <PageReader
            report={report}
            page={page}
            cited={selected}
            onPage={(p) => update({ page: selected && p === selected.page ? null : String(p) })}
          />
        )}
      </div>
    </div>
  );
}

/** The To review tab. `canReview`: Insights offer Approve and Reject. `canUpload`: All caught up offers Upload Report. */
export function ToReviewTab({ canReview, canUpload }: { canReview: boolean; canUpload: boolean }) {
  const reports = useReports();
  if (reports.isError) return <ErrorLine>{reports.error.message}. Reload the page to try again.</ErrorLine>;
  if (!reports.data)
    return (
      <div aria-busy>
        <p role="status" className="sr-only">
          Loading Insights awaiting review…
        </p>
        <SplitSkeleton listTitle="To review" />
      </div>
    );
  return <Inbox reports={reports.data.items} canReview={canReview} canUpload={canUpload} />;
}
