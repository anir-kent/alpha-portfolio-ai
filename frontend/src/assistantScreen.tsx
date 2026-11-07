import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { components } from "./api/schema";
import { Icon } from "./ui";

export type Screen = components["schemas"]["ScreenIdentity"];

/** One Screen Context a screen offers the Assistant: its identity and how the drawer names it. */
export type Published = { screen: Screen; label: string };

// A page may offer several: the Portfolio screen offers the Portfolio and, inside it, its Recommendation.
const ORDER: Record<Screen["kind"], number> = {
  queue: 0,
  portfolio: 1,
  recommendation: 2,
  approvals: 0,
  audit: 0,
  exchanges: 0,
  governance: 0,
  config: 0,
  health: 0,
};

type Registry = { published: Published[]; publish: (key: string, p: Published | null) => void };
const AssistantScreenContext = createContext<Registry>({ published: [], publish: () => {} });

/** Holds what the screens on display publish to the Assistant drawer. Lives in the app shell. */
export function AssistantScreenProvider({ children }: { children: ReactNode }) {
  const [byKey, setByKey] = useState<Record<string, Published>>({});
  const publish = useCallback((key: string, p: Published | null) => {
    setByKey((current) => {
      if (p === null) {
        if (!(key in current)) return current;
        const { [key]: _gone, ...rest } = current;
        return rest;
      }
      return { ...current, [key]: p };
    });
  }, []);
  const value = useMemo(
    () => ({
      publish,
      published: Object.values(byKey).sort((a, b) => ORDER[a.screen.kind] - ORDER[b.screen.kind]),
    }),
    [byKey, publish],
  );
  return <AssistantScreenContext.Provider value={value}>{children}</AssistantScreenContext.Provider>;
}

/** Publishes this screen's identity (and selected item) to the drawer while mounted; null publishes nothing. */
export function usePublishScreen(screen: Screen | null, label: string) {
  const { publish } = useContext(AssistantScreenContext);
  const kind = screen?.kind;
  const identity = screen ? JSON.stringify(screen) : null; // a stable dependency for an object rebuilt every render
  useEffect(() => {
    if (!kind || identity === null) return;
    publish(kind, { screen: JSON.parse(identity) as Screen, label });
    return () => publish(kind, null);
  }, [publish, kind, identity, label]);
}

/** Every Screen Context the screens on display offer, broadest first. */
export function usePublishedScreens(): Published[] {
  return useContext(AssistantScreenContext).published;
}

/** The spark toggle that points the Assistant at one item on a screen (a Queue row, a Trade Line, an Audit Event). */
export function AskButton({ pressed, onToggle, what }: { pressed: boolean; onToggle: () => void; what: string }) {
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm"
      aria-pressed={pressed}
      title={`Ask the Assistant about ${what}`}
      onClick={onToggle}
    >
      <Icon name="spark" size={12} />
      <span className="sr-only">Ask about {what}</span>
    </button>
  );
}
