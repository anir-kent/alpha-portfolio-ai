/** Single-key shortcuts for reviewing Insights from the keyboard: `j`/↓ and `k`/↑ move the selection, `a` approves and
 * `r` opens the reject dialog (Escape closes it, in the dialog itself). Every shortcut has a labelled button, and the key
 * is shown beside it with `Kbd`. A shortcut never fires while the Analyst is typing, while any dialog is open, or with a
 * modifier held, so browser and screen-reader commands pass through untouched. */
import { useEffect, useRef } from "react";

/** Elements that take typed keys themselves. A select is here too: letters jump between its options. */
const TYPING_TARGETS = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';
/** Elements that use the arrow keys themselves, such as a scrollable box of page text. */
const NATIVE_ARROWS = "[data-native-arrows]";

/** The shortcut a key press names, or null when it belongs to the page: typing, an open dialog, or a modifier. Letters
 * match either case without Shift, so Caps Lock still works. */
function shortcutKey(e: KeyboardEvent): string | null {
  if (e.defaultPrevented || e.isComposing || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return null;
  const target = e.target instanceof Element ? e.target : null;
  if (target?.closest(TYPING_TARGETS)) return null;
  if (document.querySelector('[role="dialog"]')) return null;
  if (e.key.startsWith("Arrow") && target?.closest(NATIVE_ARROWS)) return null;
  return e.key.length === 1 ? e.key.toLowerCase() : e.key;
}

/** Runs `bindings[key]` for each shortcut pressed, while mounted. `repeat` lets a held key fire again, which suits
 * moving through a list but not recording an Insight Review. Bindings are read at key time, so they may close over the
 * current render. */
export function useShortcuts(bindings: Record<string, () => void>, { repeat = false }: { repeat?: boolean } = {}) {
  const latest = useRef(bindings);
  useEffect(() => {
    latest.current = bindings;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat && !repeat) return;
      const key = shortcutKey(e);
      const run = key === null ? undefined : latest.current[key];
      if (!run) return;
      e.preventDefault();
      run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [repeat]);
}

/** A key hint beside a button's label. Hidden from assistive technology: the button carries `aria-keyshortcuts`. */
export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="kbd" aria-hidden>
      {children}
    </kbd>
  );
}
