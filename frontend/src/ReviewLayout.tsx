/** The review layout shared by Report detail and the To review tab: an Insight list beside the selected Insight and the
 * full text of its cited page, with the passage highlighted. `useReviewFlow` holds what happens around an Insight
 * Review (the actions or the read-only record, the advance to the next Insight awaiting review, the notice and focus),
 * so both views review exactly the same way and differ only in their order and where the selection goes. */
import { useEffect, useMemo, useRef, useState, type ReactNode, type Ref } from "react";
import { ReviewActions } from "./InsightReview";
import { findPassage } from "./passage";
import {
  CONFIDENCE,
  DIRECTION,
  STATUS,
  SUBJECT_KIND,
  SeedBadge,
  isAwaitingReview,
  useReportPage,
  type Insight,
  type Report,
} from "./research";
import { Empty, ErrorLine, Icon, Panel, Pill, minuteUtc } from "./ui";

const SKELETON_ROWS = 4;
const SKELETON_LINES = ["96%", "88%", "92%", "70%", "94%", "82%", "60%"];
/** The review split: stacked below 1280px, list beside detail from there up. Shared with the loading skeleton. */
export const SPLIT = "grid items-start gap-3 xl:grid-cols-[minmax(20rem,26rem)_minmax(0,1fr)]";

/** A whole number from a URL parameter (leading zeros allowed), or null. */
export const wholeNumber = (raw: string | null) => (raw && /^\d+$/.test(raw) ? Number(raw) : null);

export const pagesLabel = (n: number) => (n === 1 ? "page" : "pages");

export function ChevronLeft() {
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

/** One Insight in a list. `showStatus` is off where every Insight listed awaits review. */
export function InsightRow({
  insight,
  selected,
  onSelect,
  showStatus = true,
}: {
  insight: Insight;
  selected: boolean;
  onSelect: () => void;
  showStatus?: boolean;
}) {
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
          {showStatus && <Pill tone={status.tone}>{status.text}</Pill>}
        </span>
      </button>
    </li>
  );
}

/** The next Insight awaiting review after `current` in `order`, wrapping to the start; null when none remain. */
function nextAwaitingReview(order: Insight[], current: Insight): Insight | null {
  const at = order.findIndex((i) => i.id === current.id);
  const after = [...order.slice(at + 1), ...order.slice(0, Math.max(at, 0))];
  return after.find((i) => isAwaitingReview(i) && i.id !== current.id) ?? null;
}

/** Shown in place of the actions to anyone who cannot review Insights. */
function AwaitingReview() {
  return (
    <p className="callout callout-info">
      <Icon name="approvals" size={14} />
      Awaiting review. No Insight informs a Portfolio until a Research Analyst approves it.
    </p>
  );
}

/** The read-only record of an Insight Review: outcome, reviewer, time and note. */
function ReviewRecord({ insight }: { insight: Insight }) {
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

/** The selected Insight. `review` sits at the top: the actions while it awaits review, else its Insight Review record.
 * The pane takes focus after an Insight Review, so keyboard and screen-reader users land on what is shown next. */
export function InsightDetail({
  insight,
  review,
  ref,
  context,
}: {
  insight: Insight;
  review: ReactNode;
  ref: Ref<HTMLElement>;
  /** Above the subject, e.g. which Report the Insight comes from on To review. */
  context?: ReactNode;
}) {
  return (
    <section ref={ref} tabIndex={-1} className="panel outline-none" aria-label={`Insight ${insight.subject}`}>
      <div className="panel-body space-y-3">
        {review}
        <div>
          {context}
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
      </div>
    </section>
  );
}

/** One page of the Report's text. On the cited page the passage is highlighted and scrolled into view. */
export function PageReader({
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

/** The list and page skeletons of the review split, shown while the Report list loads. */
export function SplitSkeleton({ listTitle }: { listTitle: string }) {
  return (
    <div className={SPLIT} aria-hidden>
      <Panel title={listTitle}>
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
  );
}

type Notice = { tone: "pos" | "info"; text: string };
/** Why the selection moves: this Analyst's Insight Review was saved, or another Analyst's got there first (409). */
export type AdvanceOutcome = "reviewed" | "already-reviewed";

/** What the last Insight Review did, in text, in a polite live region. Empty renders nothing visible. */
export function ReviewNotice({ notice, onDismiss }: { notice: Notice | null; onDismiss: () => void }) {
  return (
    <div aria-live="polite" className="empty:hidden">
      {notice && (
        <p className={`callout callout-${notice.tone} items-start`}>
          <Icon name={notice.tone === "pos" ? "approvals" : "alert"} size={14} />
          <span className="flex-1">{notice.text}</span>
          <button type="button" className="btn btn-ghost btn-sm -my-1 !px-2" aria-label="Dismiss" onClick={onDismiss}>
            <Icon name="close" size={12} />
          </button>
        </p>
      )}
    </div>
  );
}

/**
 * The review flow around the selected Insight. `order` is the display order the selection advances through;
 * `onAdvance(from, next, outcome)` moves the selection once an Insight Review is confirmed (or another Analyst got there
 * first), with `next` the next Insight awaiting review after `from`, or null when none remain. On a 409 the cache still
 * shows `from` awaiting review until the refetch lands.
 *
 * Returns the notice to show, `detailRef` for the element that takes focus after an Insight Review, and `reviewFor`,
 * which renders the top of the detail pane: Approve and Reject for an Insight awaiting review (with `canReview`, the
 * session holds `insight:approve`), else
 * the read-only Insight Review record or an "awaiting review" note.
 */
export function useReviewFlow({
  order,
  selected,
  canReview,
  onAdvance,
}: {
  order: Insight[];
  selected: Insight | null;
  canReview: boolean;
  onAdvance: (from: Insight, next: Insight | null, outcome: AdvanceOutcome) => void;
}) {
  // It stays until dismissed, the next review or another selection.
  const [notice, setNotice] = useState<Notice | null>(null);
  const detailRef = useRef<HTMLElement>(null);
  const [focusRequests, setFocusRequests] = useState(0);
  useEffect(() => {
    if (focusRequests > 0) detailRef.current?.focus({ preventScroll: true });
  }, [focusRequests]);
  // A save can finish after the Analyst picked another Insight, or after a refetch moved statuses; the review callbacks
  // read what is on screen now, not what was there when Approve or Reject was pressed.
  const latest = useRef({ order, selectedId: selected?.id ?? null, onAdvance });
  useEffect(() => {
    latest.current = { order, selectedId: selected?.id ?? null, onAdvance };
  });

  /** Returns moved false, and changes nothing, when the Analyst has already moved on to another Insight. */
  const advance = (from: Insight, outcome: AdvanceOutcome): { moved: boolean; next: Insight | null } => {
    if (latest.current.selectedId !== from.id) return { moved: false, next: null };
    const next = nextAwaitingReview(latest.current.order, from);
    latest.current.onAdvance(from, next, outcome);
    setFocusRequests((n) => n + 1);
    return { moved: true, next };
  };
  const onReviewed = (reviewed: Insight) => {
    const { moved, next } = advance(reviewed, "reviewed");
    if (!moved) return;
    const outcome = reviewed.status === "approved" ? "Approved" : "Rejected";
    setNotice({
      tone: "pos",
      text: `${outcome} ${reviewed.subject} (Insight #${reviewed.id}).${next ? " Showing the next Insight awaiting review." : ""}`,
    });
  };
  const onAlreadyReviewed = (current: Insight) => {
    if (!advance(current, "already-reviewed").moved) return;
    setNotice({
      tone: "info",
      text: `Already reviewed by someone else: your Insight Review of ${current.subject} (Insight #${current.id}) was not saved. Refreshing to show theirs.`,
    });
  };

  const reviewFor = (insight: Insight): ReactNode =>
    !isAwaitingReview(insight) ? (
      <ReviewRecord insight={insight} />
    ) : canReview ? (
      <ReviewActions
        key={insight.id}
        insight={insight}
        onReviewed={onReviewed}
        onAlreadyReviewed={() => onAlreadyReviewed(insight)}
      />
    ) : (
      <AwaitingReview />
    );

  return { notice, clearNotice: () => setNotice(null), detailRef, reviewFor };
}
