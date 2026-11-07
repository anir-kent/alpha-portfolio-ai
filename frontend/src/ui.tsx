import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api } from "./api/client";
import type { components, operations } from "./api/schema";

/* ---------- formatting: figures are monospaced and right-aligned via .num ---------- */
export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const signed = (n: number, d = 1) => `${n > 0 ? "+" : ""}${n.toFixed(d)}`;
export const pp = (n: number) => `${signed(n)} pp`;
export const pct = (n: number, d = 1) => `${n.toFixed(d)}%`;
/** "2026-11-07T05:57:46.854027Z" -> "2026-11-07 05:57": a server timestamp at minute precision, still UTC. */
export const minuteUtc = (iso: string) => iso.slice(0, 16).replace("T", " ");

/* ---------- semantic pills ---------- */
export type Tone = "pos" | "warn" | "neg" | "info" | "ai" | "mute";

export function Pill({ tone = "mute", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      {children}
    </span>
  );
}

export const RULE_TONE = { pass: "pos", warning: "warn", breach: "neg" } as const satisfies Record<string, Tone>;
export const DRIFT_TONE = { ok: "pos", warn: "warn", breach: "neg" } as const satisfies Record<string, Tone>;
export const LABEL_TONE = { High: "neg", Medium: "warn", Low: "pos" } as const satisfies Record<string, Tone>;

/* ---------- layout bits ---------- */
export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-3 flex flex-wrap items-end gap-x-4 gap-y-1">
      <div className="min-w-0">
        <h1>{title}</h1>
        {sub && <p className="text-ink-2">{sub}</p>}
      </div>
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  aside,
  children,
  label,
  flush,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  label?: string;
  flush?: boolean;
}) {
  return (
    <section className="panel" aria-label={label}>
      {title && (
        <div className="panel-head">
          <h2>{title}</h2>
          {aside && <div className="ml-auto flex items-center gap-2 text-ink-2">{aside}</div>}
        </div>
      )}
      <div className={flush ? "" : "panel-body"}>{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-1 py-2 text-ink-3">{children}</p>;
}

export function ErrorLine({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="callout callout-neg">
      {children}
    </p>
  );
}

/* ---------- hover / focus peek ---------- */
/** Shows `children` in a floating card when the trigger is hovered or focused. The card stays open while the pointer is on it, so its
 *  contents (citation chips) remain interactive. Rendered in a portal and positioned from the trigger's rect, flipping above near the bottom. */
export function HoverPeek({ trigger, children, label }: { trigger: ReactNode; children: ReactNode; label: string }) {
  const id = useId();
  const anchor = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const timer = useRef<number>(undefined);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  const show = useCallback(() => {
    window.clearTimeout(timer.current);
    setOpen(true);
  }, []);
  const hide = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(false), 140);
  }, []);

  useLayoutEffect(() => {
    if (!open || !anchor.current || !card.current) return;
    const a = anchor.current.getBoundingClientRect();
    const c = card.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(a.left, window.innerWidth - c.width - 8));
    const below = a.bottom + 6;
    const top = below + c.height > window.innerHeight - 8 && a.top - c.height - 6 > 8 ? a.top - c.height - 6 : below;
    setPos({ left, top });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    // Page scroll dismisses the peek (its anchor moved), but scrolling inside the peek itself must not.
    const close = (e: Event) => {
      if (!card.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return (
    <>
      <div
        ref={anchor}
        className="peek-trigger min-w-0"
        tabIndex={0}
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        {trigger}
      </div>
      {open &&
        createPortal(
          <div
            ref={card}
            id={id}
            role="tooltip"
            className="peek panel"
            style={{ left: pos?.left ?? -9999, top: pos?.top ?? -9999, visibility: pos ? "visible" : "hidden" }}
            onMouseEnter={show}
            onMouseLeave={hide}
          >
            {children}
          </div>,
          document.body,
        )}
    </>
  );
}

/* ---------- volumetric figures ---------- */
const DIAL_TONE = {
  neg: ["#f08a80", "#b3261e"],
  warn: ["#f1c05a", "#b7791f"],
  pos: ["#5fd1a0", "#0b7a4b"],
  info: ["#8fb0ff", "#2253d4"],
} as const;

/** Semicircle speed dial, 0..max. The arc is graded, with a glowing end-stop. The value is real text for readers and tests. */
export function ScoreDial({
  value,
  max = 100,
  tone = "info",
  size = 78,
  label,
}: {
  value: number;
  max?: number;
  tone?: keyof typeof DIAL_TONE;
  size?: number;
  label?: string;
}) {
  const id = useId();
  const frac = Math.max(0, Math.min(1, value / max));
  const r = 40,
    len = Math.PI * r,
    a = Math.PI * (1 - frac);
  const [from, to] = DIAL_TONE[tone];
  return (
    <div className="inline-flex flex-col items-center" style={{ width: size }}>
      <svg
        viewBox="0 0 100 56"
        width={size}
        height={size * 0.56}
        role="img"
        aria-label={`${label ?? "Score"} ${value.toFixed(1)} of ${max}`}
      >
        <defs>
          <linearGradient id={id} x1="0" x2="1">
            <stop offset="0" stopColor={from} />
            <stop offset="1" stopColor={to} />
          </linearGradient>
          <filter id={`${id}g`} x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="2.2" />
          </filter>
        </defs>
        <path
          d="M10,50 A40,40 0 0 1 90,50"
          fill="none"
          stroke="rgb(31 38 80 / 0.09)"
          strokeWidth="9"
          strokeLinecap="round"
        />
        <path
          d="M10,50 A40,40 0 0 1 90,50"
          fill="none"
          stroke="rgb(255 255 255 / 0.9)"
          strokeWidth="1"
          strokeLinecap="round"
          transform="translate(0 4.6)"
          opacity="0.7"
        />
        {frac > 0 && (
          <path
            d="M10,50 A40,40 0 0 1 90,50"
            fill="none"
            stroke={`url(#${id})`}
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={`${len * frac} ${len}`}
            style={{ transition: "stroke-dasharray 400ms ease-out" }}
          />
        )}
        {frac > 0 && (
          <circle
            cx={50 + r * Math.cos(a)}
            cy={50 - r * Math.sin(a)}
            r="3.4"
            fill="#fff"
            stroke={to}
            strokeWidth="1.6"
          />
        )}
        {frac > 0 && (
          <circle
            cx={50 + r * Math.cos(a)}
            cy={50 - r * Math.sin(a)}
            r="5"
            fill={to}
            opacity="0.35"
            filter={`url(#${id}g)`}
          />
        )}
        <text
          x="50"
          y="47"
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          fontSize="15"
          fontWeight="700"
          fill="var(--color-ink)"
        >
          {value.toFixed(1)}
        </text>
      </svg>
    </div>
  );
}

/** Diverging delta bar on a faint grid: zero in the middle, emerald to the right, crimson to the left unless `tone` overrides. */
export function DeltaBar({
  value,
  max,
  tone,
  width = "7rem",
  height = "0.6rem",
}: {
  value: number;
  max: number;
  tone?: "pos" | "neg" | "warn";
  width?: string;
  height?: string;
}) {
  const t = tone ?? (value >= 0 ? "pos" : "neg");
  const grad = {
    pos: "linear-gradient(to bottom, #5fd1a0, #0b7a4b)",
    neg: "linear-gradient(to bottom, #ef7a70, #b3261e)",
    warn: "linear-gradient(to bottom, #f1c05a, #b7791f)",
  }[t];
  const w = Math.min(1, Math.abs(value) / max) * 50;
  return (
    <div
      className="gridtex relative inline-block rounded-full align-middle"
      style={{ width, height }}
      role="img"
      aria-label={`delta ${value.toFixed(2)}`}
    >
      <div
        className="rod absolute inset-y-0"
        style={{
          background: grad,
          width: `${w}%`,
          left: value >= 0 ? "50%" : `${50 - w}%`,
          transition: "width 240ms ease-out",
        }}
      />
      <div className="absolute inset-y-[-2px] left-1/2 w-px bg-ink-3/60" />
    </div>
  );
}

/* ---------- icons: plain UI glyphs (16px, currentColor) ---------- */
const PATHS: Record<string, string> = {
  queue: "M2 3.5h12M2 8h12M2 12.5h7",
  approvals: "M3 8.5l3 3 7-7",
  audit: "M8 2l5 2v4c0 3-2.2 5.3-5 6-2.8-.7-5-3-5-6V4l5-2z",
  governance: "M3 13V7m5 6V3m5 10V9",
  config: "M3 5h10M3 11h10M6 3v4M10 9v4",
  health: "M2 8h3l2-4 2 8 2-4h3",
  research: "M4 1.5h5.5L12.5 4.5v10h-8.5zM9.5 1.5v3h3M6.5 8h4M6.5 10.5h4",
  chevron: "M6 3l5 5-5 5",
  close: "M3 3l10 10M13 3L3 13",
  lock: "M4.5 7V5a3.5 3.5 0 017 0v2M3.5 7h9v6.5h-9z",
  alert: "M8 2l6.5 11.5h-13L8 2zM8 6.5v3M8 11.5v.1",
  spark: "M8 1.5l1.6 4.2 4.2 1.6-4.2 1.6L8 13.1 6.4 8.9 2.2 7.3l4.2-1.6L8 1.5z",
  link: "M6.5 9.5l3-3M5.5 7L4 8.5a2.5 2.5 0 003.5 3.5L9 10.5M10.5 9L12 7.5A2.5 2.5 0 008.5 4L7 5.5",
};
export function Icon({ name, size = 15 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name] ?? PATHS.queue} />
    </svg>
  );
}

/* ---------- citations: chip that expands the quoted source inline ---------- */
export function CitationChip({ kind, label, quote }: { kind: "report" | "engine"; label: string; quote?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-block align-baseline">
      <button
        type="button"
        className={`chip ${kind === "report" ? "chip-report" : "chip-engine"}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Icon name={kind === "report" ? "link" : "spark"} size={11} />
        {label}
      </button>
      {open && quote && <span className="quote block">&ldquo;{quote}&rdquo;</span>}
    </span>
  );
}

type Cite = components["schemas"]["ReportCitation"] | components["schemas"]["EngineCitation"];
export function Citations({ citations }: { citations: Cite[] }) {
  if (citations.length === 0) return <Pill tone="neg">no citation</Pill>;
  return (
    <span className="inline-flex flex-wrap items-start gap-1">
      {citations.map((c, i) =>
        c.kind === "report" ? (
          <CitationChip key={i} kind="report" label={`${c.report_id} p.${c.page}`} quote={c.quote} />
        ) : (
          <CitationChip key={i} kind="engine" label={c.figure} />
        ),
      )}
    </span>
  );
}

/* ---------- queue snapshot shared by the queue page and the global status strip ---------- */
export type QueueParams = NonNullable<operations["getQueue"]["parameters"]["query"]>;
export function useQueue(filters: QueueParams) {
  return useQuery({
    queryKey: ["queue", filters],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/queue", { params: { query: filters } });
      if (error || !data) throw new Error("Could not load the queue");
      return data;
    },
  });
}

/* ---------- drawer: portalled, closes on Escape and the scrim ---------- */
export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Portalled to <body>: the glass panels use backdrop-filter, which would otherwise become the containing block of a fixed drawer.
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="panel-head !px-4 !py-2.5">
          <h2 className="!text-[1.0769rem]">{title}</h2>
          <button type="button" className="btn btn-ghost btn-sm ml-auto" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">{children}</div>
      </aside>
    </>,
    document.body,
  );
}

/** Enabled controls a user can Tab to; anything taken out of the tab order (tabindex -1, e.g. a hidden file input) is not. */
const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]",
]
  .map((s) => `${s}:not([tabindex='-1'])`)
  .join(", ");

/** A dialog's Tab handler: Tab and Shift+Tab cycle through the dialog's enabled controls and never leave it. With none
 * enabled (e.g. while it saves), focus stays on the dialog itself. */
export function trapTab(e: { key: string; shiftKey: boolean; preventDefault: () => void }, dialog: HTMLElement | null) {
  if (e.key !== "Tab" || !dialog) return;
  const focusable = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)];
  if (focusable.length === 0) return e.preventDefault();
  const first = focusable[0],
    last = focusable[focusable.length - 1];
  if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
