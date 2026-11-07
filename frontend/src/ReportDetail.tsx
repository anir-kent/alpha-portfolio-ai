/** Report detail: a Report's metadata and every Insight in the review layout, each beside the full text of its cited
 * page with the passage highlighted. Read-only; the Insight Review actions land in the detail pane (ticket 04). A
 * failed extraction offers Upload again. Selection, status filter and the page being read all live in the URL, so a reload or a shared link restores them. */
import { useEffect, useMemo, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { findPassage } from "./passage";
import {
  CONFIDENCE,
  DIRECTION,
  KIND_LABEL,
  Outcome,
  STATUS,
  SUBJECT_KIND,
  SeedBadge,
  insightCounts,
  pageOrder,
  useReportPage,
  useReports,
  type Insight,
  type InsightStatus,
  type Report,
} from "./research";
import { Empty, ErrorLine, Icon, PageHeader, Panel, Pill, minuteUtc } from "./ui";
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
const SKELETON_ROWS = 4;
const SKELETON_LINES = ["96%", "88%", "92%", "70%", "94%", "82%", "60%"];
/** The review split: stacked below 1280px, list beside detail from there up. Shared with the loading skeleton. */
const SPLIT = "grid items-start gap-3 xl:grid-cols-[minmax(20rem,26rem)_minmax(0,1fr)]";

/** A whole number from a URL parameter (leading zeros allowed), or null. */
const wholeNumber = (raw: string | null) => (raw && /^\d+$/.test(raw) ? Number(raw) : null);

const pagesLabel = (n: number) => (n === 1 ? "page" : "pages");

function ChevronLeft() {
  return (
    <span className="inline-flex rotate-180" aria-hidden>
      <Icon name="chevron" size={13} />
    </span>
  );
}

/** Direction and confidence, the claim an Analyst reviews. */
function ClaimPills({ insight }: { insight: Insight }) {
  return (
    <>
      <Pill tone={DIRECTION[insight.direction].tone}>{DIRECTION[insight.direction].text}</Pill>
      <Pill tone={CONFIDENCE[insight.confidence].tone}>{CONFIDENCE[insight.confidence].text}</Pill>
    </>
  );
}

function BackLink() {
  return (
    <Link to="/research" className="btn btn-ghost btn-sm mb-1 !pl-1.5">
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

function InsightRow({ insight, selected, onSelect }: { insight: Insight; selected: boolean; onSelect: () => void }) {
  const status = STATUS[insight.status];
  return (
    <li>
      <button type="button" className="insight-row" aria-current={selected || undefined} onClick={onSelect}>
        <span className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate font-semibold">{insight.subject}</span>
          <span className="mono shrink-0 text-ink-3">p. {insight.page}</span>
        </span>
        <span className="flex flex-wrap gap-1">
          <ClaimPills insight={insight} />
          <Pill tone={status.tone}>{status.text}</Pill>
        </span>
      </button>
    </li>
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

/** The read-only record of an Insight Review: outcome, reviewer, time and note. */
function ReviewRecord({ insight }: { insight: Insight }) {
  if (insight.status === "pending")
    return (
      <p className="callout callout-info">
        <Icon name="approvals" size={14} />
        Awaiting review. No Insight informs a Portfolio until a Research Analyst approves it.
      </p>
    );
  const status = STATUS[insight.status];
  return (
    <section aria-label="Insight Review" className="panel">
      <div className="panel-body">
        <p className="eyebrow mb-2">Insight Review</p>
        <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5">
          <dt className="text-ink-3">Outcome</dt>
          <dd>
            <Pill tone={status.tone}>{status.text}</Pill>
          </dd>
          <dt className="text-ink-3">Reviewer</dt>
          <dd className="mono">{insight.decided_by ?? "—"}</dd>
          <dt className="text-ink-3">Reviewed (UTC)</dt>
          <dd className="mono" title={insight.decided_at ?? undefined}>
            {insight.decided_at ? minuteUtc(insight.decided_at) : "—"}
          </dd>
          <dt className="text-ink-3">Note</dt>
          <dd>
            {insight.decision_note ? insight.decision_note : <span className="text-ink-3">No note recorded</span>}
          </dd>
        </dl>
      </div>
    </section>
  );
}

function InsightDetail({ insight }: { insight: Insight }) {
  return (
    <section className="panel" aria-label={`Insight ${insight.subject}`}>
      <div className="panel-body space-y-3">
        <div>
          <p className="eyebrow">
            {SUBJECT_KIND[insight.subject_kind]} · Insight <span className="mono">#{insight.id}</span>
          </p>
          <h2 className="!text-[1.3846rem] !font-semibold">{insight.subject}</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <ClaimPills insight={insight} />
            <Pill tone="mute">
              Cited on page <span className="mono">{insight.page}</span>
            </Pill>
            {insight.human_verified && <SeedBadge what="Insight" />}
          </div>
        </div>
        <figure>
          <figcaption className="eyebrow">Cited passage</figcaption>
          <blockquote className="quote">{insight.passage}</blockquote>
        </figure>
        <ReviewRecord insight={insight} />
      </div>
    </section>
  );
}

/** One page of the Report's text. On the cited page the passage is highlighted and scrolled into view. */
function PageReader({
  report,
  page,
  cited,
  onPage,
}: {
  report: Report;
  page: number;
  cited: Insight | null;
  onPage: (page: number) => void;
}) {
  const text = useReportPage(report.id, page);
  const onCitedPage = cited !== null && cited.page === page;
  const match = useMemo(
    () => (onCitedPage && text.data ? findPassage(text.data.text, cited.passage) : null),
    [onCitedPage, text.data, cited],
  );
  const boxRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLElement>(null);

  // Scroll inside the page box only, so the window and the Insight list stay where the Analyst left them.
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const mark = markRef.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollTo({ top: mark ? Math.max(0, mark.offsetTop - box.clientHeight / 3) : 0 });
    // When the panes stack, or a long review record pushes the page down, bring the passage onto the screen too.
    mark?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }, [match, text.data]);

  const pages = Array.from({ length: report.page_count }, (_, i) => i + 1);
  return (
    <section className="panel" aria-label={`Report page ${page}`}>
      <div className="panel-head flex-wrap">
        <h2>
          Page <span className="mono">{page}</span>{" "}
          <span className="font-normal text-ink-3">
            of <span className="mono">{report.page_count}</span>
          </span>
        </h2>
        {onCitedPage && <Pill tone="ai">Cited page</Pill>}
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {cited && !onCitedPage && (
            <button type="button" className="btn btn-sm" onClick={() => onPage(cited.page)}>
              Back to cited page <span className="mono">{cited.page}</span>
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm !px-2"
            aria-label="Previous page"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            <ChevronLeft />
          </button>
          <label className="flex items-center gap-1.5 text-ink-3">
            <span className="sr-only">Read page</span>
            <select className="field btn-sm !h-7 !pr-2" value={page} onChange={(e) => onPage(Number(e.target.value))}>
              {pages.map((p) => (
                <option key={p} value={p}>
                  Page {p}
                  {cited?.page === p ? " (cited)" : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-ghost btn-sm !px-2"
            aria-label="Next page"
            disabled={page >= report.page_count}
            onClick={() => onPage(page + 1)}
          >
            <Icon name="chevron" size={13} />
          </button>
        </div>
      </div>
      <div className="panel-body space-y-2">
        {onCitedPage && text.data && !match && (
          <p role="status" className="callout callout-warn">
            <Icon name="alert" size={14} />
            Cited passage not found verbatim on page {page}. The page is shown without a highlight; check the citation.
          </p>
        )}
        {text.isError ? (
          <div className="space-y-2">
            <ErrorLine>Could not load page {page} of this Report.</ErrorLine>
            <button type="button" className="btn btn-sm" onClick={() => void text.refetch()}>
              Try again
            </button>
          </div>
        ) : (
          <div
            ref={boxRef}
            className="page-text"
            tabIndex={0}
            aria-label={`Text of page ${page}`}
            aria-busy={text.isLoading}
          >
            {text.isLoading && (
              <div className="space-y-2.5 py-1" aria-hidden>
                {SKELETON_LINES.map((w, i) => (
                  <span key={i} className="skeleton" style={{ width: w }} />
                ))}
              </div>
            )}
            {text.isLoading && (
              <p role="status" className="sr-only">
                Loading page {page}…
              </p>
            )}
            {text.data &&
              (text.data.text.trim() === "" ? (
                <Empty>This page has no extractable text.</Empty>
              ) : match ? (
                <>
                  {text.data.text.slice(0, match.start)}
                  <mark ref={markRef} className="cited">
                    {text.data.text.slice(match.start, match.end)}
                  </mark>
                  {text.data.text.slice(match.end)}
                </>
              ) : (
                text.data.text
              ))}
          </div>
        )}
      </div>
    </section>
  );
}

function ReportDetail({ report, canUpload }: { report: Report; canUpload: boolean }) {
  const [params, setParams] = useSearchParams();
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

  // Replace rather than push: Back leaves the Report instead of stepping through every click.
  const update = (changes: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(changes)) {
          if (v === null) next.delete(k);
          else next.set(k, v);
        }
        return next;
      },
      { replace: true },
    );

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
            onSelect={(id) => update({ insight: String(id), page: null })}
          />
        )}
        <div className="min-w-0 space-y-3">
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
          {selected && <InsightDetail insight={selected} />}
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
      <div className={SPLIT} aria-hidden>
        <Panel title="Insights">
          <div className="space-y-4">
            {Array.from({ length: SKELETON_ROWS }, (_, i) => (
              <div key={i} className="space-y-1.5">
                <span className="skeleton" style={{ width: "65%" }} />
                <span className="skeleton" style={{ width: "85%" }} />
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Page">
          <div className="space-y-2.5">
            {SKELETON_LINES.map((w, i) => (
              <span key={i} className="skeleton" style={{ width: w }} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/** Route element for /research/reports/:reportId. `canUpload`: a failed extraction offers Upload again. */
export function ReportDetailPage({ canUpload }: { canUpload: boolean }) {
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
  return <ReportDetail report={report} canUpload={canUpload} />;
}
