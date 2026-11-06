import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import { useMatch } from "react-router-dom";
import { api } from "./api/client";
import type { components } from "./api/schema";
import { Icon } from "./ui";

type Turn = components["schemas"]["Turn"];
type Screen = components["schemas"]["ScreenIdentity"];
interface Asked {
  question: string;
  turn: Turn;
}

/** The screen identity the current route publishes to the Assistant, and how the drawer names it. Null off a supported screen. */
function useCurrentScreen(): { screen: Screen; label: string } | null {
  const portfolio = useMatch("/portfolios/:id");
  const id = portfolio?.params.id;
  if (id)
    return {
      screen: { kind: "portfolio", entity_ids: { portfolio_id: id }, selected_item: null },
      label: `Portfolio ${id}`,
    };
  return null;
}

/** Model-written Markdown. Raw HTML in it is dropped, never rendered. */
function AnswerMarkdown({ text }: { text: string }) {
  return (
    <div className="assistant-md">
      <Markdown skipHtml>{text}</Markdown>
    </div>
  );
}

function TurnView({ question, turn, onFollowUp }: Asked & { onFollowUp: (q: string) => void }) {
  return (
    <li className="space-y-1.5">
      <p className="ml-auto w-fit max-w-[90%] rounded-2xl bg-brand/10 px-3 py-1.5">{question}</p>
      {turn.outcome === "answered" && turn.answer && (
        <div className="space-y-1.5">
          <AnswerMarkdown text={turn.answer.markdown} />
          {turn.answer.follow_up_questions.length > 0 && (
            <ul className="flex flex-wrap gap-1" aria-label="Follow-up questions">
              {turn.answer.follow_up_questions.map((q) => (
                <li key={q}>
                  <button type="button" className="chip chip-engine" onClick={() => onFollowUp(q)}>
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {turn.outcome === "refused" && turn.answer && <p className="callout callout-warn">{turn.answer.markdown}</p>}
      {turn.outcome === "failed" && <p className="callout callout-neg">{turn.message}</p>}
    </li>
  );
}

/** The Assistant: a collapsible, non-modal panel in the app shell that stays open across navigation. Read-only. */
export function AssistantDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const current = useCurrentScreen();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Asked[]>([]);
  const ask = useMutation({
    mutationFn: async ({ question, screen }: { question: string; screen: Screen }) => {
      const { data, error } = await api.POST("/api/assistant/questions", { body: { question, screen } });
      if (error || !data) throw new Error("The Assistant couldn't answer, try again.");
      return { question, turn: data };
    },
    onSuccess: (asked) => {
      setTurns((ts) => [...ts, asked]);
      setQuestion("");
    },
  });
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const send = () => {
    const q = question.trim();
    if (!q || !current || ask.isPending) return;
    ask.mutate({ question: q, screen: current.screen });
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
      <div className="flex-1 overflow-y-auto p-4">
        {turns.length === 0 && !ask.isPending && (
          <p className="text-ink-3">
            Ask about the data on this screen. The Assistant explains engine figures; it gives no investment advice and
            changes nothing.
          </p>
        )}
        <ol className="space-y-4">
          {turns.map((t, i) => (
            <TurnView key={i} {...t} onFollowUp={setQuestion} />
          ))}
        </ol>
        <div aria-live="polite">
          {ask.isPending && <p className="mt-3 text-ink-3">Thinking…</p>}
          {ask.isError && <p className="callout callout-neg mt-3">{ask.error.message}</p>}
        </div>
      </div>
      <form
        className="space-y-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <label className="label">
          Question
          <textarea
            className="field min-h-[4.5rem]"
            value={question}
            disabled={!current}
            placeholder={current ? `Ask about ${current.label}` : "Open a Portfolio to ask about it"}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
        </label>
        <button className="btn btn-primary w-full" disabled={!current || !question.trim() || ask.isPending}>
          Send
        </button>
      </form>
    </aside>
  );
}
