import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import Markdown from "react-markdown";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { usePublishedScreens, type Published, type Screen } from "./assistantScreen";
import { CitationChip, Icon, Pill } from "./ui";

type Turn = components["schemas"]["Turn"];
type Conversation = components["schemas"]["Conversation"];
type ClaimResult = components["schemas"]["ClaimResult"];

/** Cached under this key, so logout (which drops every query but "me") clears the Conversation from the page too. */
const CONVERSATION_KEY = ["assistant-conversation"];
const FAILED_MESSAGE = "The Assistant couldn't answer, try again.";
/** A usage limit the server applied (429). Cached so logout clears it with the Conversation; a new login starts a new
 * Conversation, and with it a fresh per-Conversation count. */
const LIMIT_KEY = ["assistant-limit"];

type Limit = { message: string; until: number | null }; // until: epoch ms from Retry-After; null lasts the login

/** The server refused the Question outright (400 too long, 429 a limit), with a plain message. Nothing was stored, so
 * there is no turn to show and retrying the same request won't help. */
class LimitRejection extends Error {
  constructor(
    message: string,
    readonly limit: Limit | null,
  ) {
    super(message);
  }
}

/** The limit in force, cleared when its Retry-After passes. */
function useLimit(): Limit | null {
  const qc = useQueryClient();
  const { data: limit } = useQuery<Limit | null>({
    queryKey: LIMIT_KEY,
    queryFn: () => null, // set only from a 429; there is nothing to fetch
    staleTime: Infinity,
  });
  useEffect(() => {
    if (!limit || limit.until === null) return;
    const id = window.setTimeout(() => qc.setQueryData(LIMIT_KEY, null), Math.max(limit.until - Date.now(), 0));
    return () => window.clearTimeout(id);
  }, [limit, qc]);
  return limit ?? null;
}

/** How the drawer names a turn's context: the server's label, or for a turn whose screen the user couldn't read
 * (the server names nothing) the identity the browser itself sent. */
function turnLabel(turn: Turn): string {
  return turn.context_label ?? `${turn.screen.kind} ${Object.values(turn.screen.entity_ids).join(", ")}`;
}

function sameScreen(a: Screen, b: Screen): boolean {
  return (
    JSON.stringify([a.kind, a.entity_ids, a.selected_item]) === JSON.stringify([b.kind, b.entity_ids, b.selected_item])
  );
}

/** The context the drawer asks against, among those the screens on display publish. A newly selected item (a Queue
 * row, a Trade Line) takes over, since selecting is how the user says what the Question is about; otherwise the
 * user's own pick, else the broadest. Null off a screen that publishes none. */
function useCurrentScreen(): {
  current: Published | null;
  offered: Published[];
  choose: (kind: Screen["kind"]) => void;
} {
  const offered = usePublishedScreens();
  const [chosen, setChosen] = useState<Screen["kind"] | null>(null);
  // Adjusted while rendering (not in an effect): only a change of selection moves the pick.
  const selection = offered.map((p) => `${p.screen.kind}:${p.screen.selected_item ?? ""}`).join("|");
  const [seenSelection, setSeenSelection] = useState(selection);
  if (selection !== seenSelection) {
    setSeenSelection(selection);
    const selected = offered.filter((p) => p.screen.selected_item).at(-1);
    if (selected) setChosen(selected.screen.kind);
  }
  const current = offered.find((p) => p.screen.kind === chosen) ?? offered[0] ?? null;
  return { current, offered, choose: setChosen };
}

/** Model-written Markdown. Raw HTML in it is dropped, never rendered. */
function AnswerMarkdown({ text }: { text: string }) {
  return (
    <div className="assistant-md">
      <Markdown skipHtml>{text}</Markdown>
    </div>
  );
}

/** The route of the screen each kind of Screen Context is built from, so an engine figure chip can go back to it. */
const SCREEN_ROUTES: Record<Screen["kind"], (ids: Screen["entity_ids"]) => string> = {
  queue: () => "/queue",
  portfolio: (ids) => `/portfolios/${encodeURIComponent(ids.portfolio_id ?? "")}`,
  // The Recommendation is shown on its Portfolio's screen.
  recommendation: (ids) => `/portfolios/${encodeURIComponent(ids.portfolio_id ?? "")}`,
  approvals: () => "/approvals",
  audit: () => "/audit",
  exchanges: () => "/llm-exchanges",
  governance: () => "/governance",
  config: () => "/config",
  health: () => "/health",
};

/** Lookup figures retain their Portfolio source even when the Question was asked elsewhere. */
function figureRoute(figure: string, screen: Screen): string {
  const portfolio = /^portfolio\.([^.]+)\./.exec(figure);
  return portfolio ? `/portfolios/${encodeURIComponent(portfolio[1])}` : SCREEN_ROUTES[screen.kind](screen.entity_ids);
}

/** One Claim with its citation chips: a Report citation opens the quoted passage, an engine figure goes to the screen
 * it came from. A Claim that failed grounding stays in the Answer, marked in place with its reasons. */
function ClaimView({ claim, screen }: { claim: ClaimResult; screen: Screen }) {
  return (
    <li className={claim.grounded ? "" : "assistant-claim-ungrounded"}>
      <span className="text-ink">{claim.text}</span>{" "}
      {!claim.grounded && (
        <Pill tone="neg">
          <Icon name="alert" size={11} />
          ungrounded
        </Pill>
      )}{" "}
      <span className="inline-flex flex-wrap items-start gap-1">
        {claim.citations.map((citation, n) =>
          citation.kind === "report" ? (
            <CitationChip
              key={n}
              kind="report"
              label={`${citation.report_id} p.${citation.page}`}
              quote={citation.quote}
            />
          ) : (
            <Link
              key={n}
              className="chip chip-engine"
              to={figureRoute(citation.figure, screen)}
              title={`Engine figure: ${citation.figure}`}
            >
              <Icon name="spark" size={11} />
              {citation.figure}
            </Link>
          ),
        )}
      </span>
      {claim.issues.map((issue) => (
        <p key={issue.code + issue.message} className="text-neg">
          {issue.message}
        </p>
      ))}
    </li>
  );
}

/** Marks where the Conversation moved to another screen; each earlier turn stays tied to its own context. */
function ContextDivider({ turn }: { turn: Turn }) {
  return (
    <li className="assistant-divider" role="separator" aria-label={`Context changed to ${turnLabel(turn)}`}>
      <span>Context changed · {turnLabel(turn)}</span>
    </li>
  );
}

/** The current screen kind's three Suggested Questions; clicking one asks it. In replay mode only these are answered. */
function SuggestedQuestions({
  kind,
  onAsk,
  busy,
}: {
  kind: Screen["kind"];
  onAsk: (q: string) => void;
  busy: boolean;
}) {
  const suggested = useQuery({
    queryKey: ["assistant-suggested-questions", kind],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/assistant/suggested-questions", { params: { query: { kind } } });
      if (error || !data) throw new Error("Suggested Questions couldn't be loaded.");
      return data.questions;
    },
    staleTime: Infinity, // defined in code next to each Screen Context builder: they change only with a deploy
  });
  if (!suggested.data) return null;
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Suggested Questions">
      {suggested.data.map((q) => (
        <li key={q}>
          <button type="button" className="chip chip-engine" onClick={() => onAsk(q)} disabled={busy}>
            {q}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The safe failure message with a retry button. Retry asks again as a new turn; the failed one stays in the record. */
function FailedCallout({ message, onRetry, busy }: { message: string; onRetry: () => void; busy: boolean }) {
  return (
    <div className="callout callout-neg flex items-center gap-2">
      <p className="flex-1">{message}</p>
      <button type="button" className="btn btn-sm" onClick={onRetry} disabled={busy}>
        Retry
      </button>
    </div>
  );
}

function TurnView({
  turn,
  onFollowUp,
  onRetry,
  busy,
}: {
  turn: Turn;
  onFollowUp: (q: string) => void;
  onRetry: (turn: Turn) => void;
  busy: boolean;
}) {
  return (
    <li className="space-y-1.5">
      <p className="ml-auto w-fit max-w-[90%] rounded-2xl bg-brand/10 px-3 py-1.5">{turn.question}</p>
      {turn.outcome === "answered" && turn.answer && (
        <div className="space-y-1.5">
          <AnswerMarkdown text={turn.answer.markdown} />
          {turn.answer.claims.length > 0 && (
            <ul className="assistant-claims" aria-label="Claims">
              {turn.answer.claims.map((c) => (
                <ClaimView key={c.index} claim={c} screen={turn.screen} />
              ))}
            </ul>
          )}
          {turn.answer.follow_up_questions.length > 0 && (
            <ul className="flex flex-wrap gap-1" aria-label="Follow-up questions">
              {turn.answer.follow_up_questions.map((q) => (
                <li key={q}>
                  <button type="button" className="chip chip-engine" onClick={() => onFollowUp(q)} disabled={busy}>
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {turn.outcome === "refused" && turn.answer && <p className="callout callout-warn">{turn.answer.markdown}</p>}
      {turn.answer && turn.trajectory && (
        <details className="rounded-lg border border-line px-3 py-2 text-ink-3">
          <summary className="cursor-pointer text-ink">How I answered</summary>
          <ol className="mt-2 list-inside list-decimal space-y-1">
            {turn.trajectory.steps.map((step, index) => (
              <li key={index}>
                {step.kind === "model_request" ? (
                  "Model request"
                ) : (
                  <>
                    <span className="font-medium text-ink">{step.name}</span>
                    {step.arguments &&
                      ` (${Object.entries(step.arguments)
                        .map(([key, value]) => `${key}: ${value}`)
                        .join(", ")})`}
                    {step.result_summary && ` · ${step.result_summary}`}
                  </>
                )}
              </li>
            ))}
          </ol>
          <p className="mt-2">
            Requests: {turn.trajectory.requests_used} / {turn.trajectory.request_limit}
            {" · "}Tokens: {turn.trajectory.input_tokens} in / {turn.trajectory.output_tokens} out
          </p>
        </details>
      )}
      {turn.outcome === "failed" && (
        <FailedCallout message={turn.message ?? FAILED_MESSAGE} onRetry={() => onRetry(turn)} busy={busy} />
      )}
    </li>
  );
}

/** The Assistant: a collapsible, non-modal panel in the app shell that stays open across navigation. Read-only. */
export function AssistantDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { current, offered, choose } = useCurrentScreen();
  const [question, setQuestion] = useState("");
  const qc = useQueryClient();
  // The server keeps the Conversation for the login session, so a reload restores it from here. 204 means none yet.
  const conversation = useQuery({
    queryKey: CONVERSATION_KEY,
    queryFn: async (): Promise<Conversation | null> => {
      const { data, error } = await api.GET("/api/assistant/conversation");
      if (error) throw new Error("The Conversation couldn't be loaded.");
      return data ?? null;
    },
    staleTime: Infinity, // only this drawer adds turns, and it writes them into the cache itself
  });
  const turns = conversation.data?.turns ?? [];
  const limit = useLimit();
  const ask = useMutation({
    mutationFn: async ({ question, screen }: { question: string; screen: Screen }) => {
      const { data, error, response } = await api.POST("/api/assistant/questions", { body: { question, screen } });
      if (response.status === 400 || response.status === 429) {
        const message =
          (error && "detail" in error && typeof error.detail === "string" && error.detail) || FAILED_MESSAGE;
        const retryAfter = Number(response.headers.get("Retry-After"));
        const until = retryAfter > 0 ? Date.now() + retryAfter * 1000 : null;
        throw new LimitRejection(message, response.status === 429 ? { message, until } : null);
      }
      if (error || !data) throw new Error(FAILED_MESSAGE);
      return data;
    },
    onError: (e) => {
      if (e instanceof LimitRejection && e.limit) qc.setQueryData<Limit>(LIMIT_KEY, e.limit);
    },
    onSuccess: async (turn) => {
      const known = qc.getQueryData<Conversation | null>(CONVERSATION_KEY);
      if (known) qc.setQueryData<Conversation>(CONVERSATION_KEY, { ...known, turns: [...known.turns, turn] });
      // The first turn created the Conversation; awaiting the refetch keeps "Thinking…" up until it shows.
      else await qc.invalidateQueries({ queryKey: CONVERSATION_KEY });
    },
  });
  // Nothing can be asked while a request is in flight or a limit applies.
  const blocked = ask.isPending || limit !== null;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const send = () => {
    const q = question.trim();
    if (!q || !current || blocked) return;
    // Clearing only here keeps whatever is being typed when a retry lands.
    ask.mutate({ question: q, screen: current.screen }, { onSuccess: () => setQuestion("") });
  };
  // A Suggested Question or a follow-up is asked as is, about the current screen, leaving the Question box alone.
  const askNow = (q: string) => {
    if (current && !blocked) ask.mutate({ question: q, screen: current.screen });
  };
  // The same Question and screen identity as the failed turn, even after moving to another screen.
  const retry = (turn: Turn) => {
    if (!blocked) ask.mutate({ question: turn.question, screen: turn.screen });
  };
  return (
    <aside id="assistant-drawer" className="assistant panel" aria-label="Assistant" hidden={!open}>
      <div className="panel-head !px-4 !py-2.5">
        <Icon name="spark" />
        <div className="min-w-0">
          <h2 className="!text-[1.0769rem]">Assistant</h2>
          <p className="truncate text-ink-3" aria-live="polite">
            {current ? current.label : "No context on this screen"}
          </p>
        </div>
        <button type="button" className="btn btn-ghost btn-sm ml-auto" onClick={onClose} aria-label="Close Assistant">
          <Icon name="close" />
        </button>
      </div>
      {offered.length > 1 && (
        <div className="seg mx-4 mt-2.5 w-fit" role="group" aria-label="Ask about">
          {offered.map((p) => (
            <button
              key={p.screen.kind}
              type="button"
              aria-pressed={p.screen.kind === current?.screen.kind}
              onClick={() => choose(p.screen.kind)}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-4">
        {conversation.isError && <p className="callout callout-neg mb-3">{conversation.error.message}</p>}
        {turns.length === 0 && !ask.isPending && !conversation.isPending && (
          <p className="text-ink-3">
            Ask about the data on this screen. The Assistant explains engine figures; it gives no investment advice and
            changes nothing.
          </p>
        )}
        <ol className="space-y-4">
          {turns.map((t, i) => (
            <Fragment key={t.seq}>
              {i > 0 && !sameScreen(turns[i - 1].screen, t.screen) && <ContextDivider turn={t} />}
              <TurnView turn={t} onFollowUp={askNow} onRetry={retry} busy={blocked || !current} />
            </Fragment>
          ))}
        </ol>
        <div aria-live="polite">
          {ask.isPending && <p className="mt-3 text-ink-3">Thinking…</p>}
          {limit ? (
            <p className="callout callout-warn mt-3" role="status">
              {limit.message}
            </p>
          ) : ask.error instanceof LimitRejection ? (
            // A limit's own message shows above while it applies; once it lifts, the old 429 is no longer news.
            !ask.error.limit && <p className="callout callout-neg mt-3">{ask.error.message}</p>
          ) : (
            ask.isError && (
              <div className="mt-3">
                {/* The request never became a turn (network or server error): retry sends the same Question again. */}
                <FailedCallout message={ask.error.message} onRetry={() => ask.mutate(ask.variables)} busy={false} />
              </div>
            )
          )}
        </div>
      </div>
      <form
        className="space-y-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        {current && <SuggestedQuestions kind={current.screen.kind} onAsk={askNow} busy={blocked} />}
        <label className="label">
          Question
          <textarea
            className="field min-h-[4.5rem]"
            value={question}
            disabled={!current || limit !== null}
            placeholder={
              limit
                ? "Asking is paused by a usage limit"
                : current
                  ? `Ask about ${current.label}`
                  : "Open the Queue or a Portfolio to ask about it"
            }
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
        </label>
        <button className="btn btn-primary w-full" disabled={!current || !question.trim() || blocked}>
          Send
        </button>
      </form>
    </aside>
  );
}
