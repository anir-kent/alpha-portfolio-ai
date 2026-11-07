// Navigation is gated by server-issued permissions (from /api/auth/me); the
// server still enforces every action, this only decides what to show.
export interface NavItem {
  to: string;
  label: string;
  requires: string;
}

export const NAV: NavItem[] = [
  { to: "/queue", label: "Queue", requires: "queue:read" },
  { to: "/approvals", label: "Approvals", requires: "approvals:read" },
  { to: "/research", label: "Research", requires: "report:read" },
  { to: "/audit", label: "Audit", requires: "audit:read" },
  { to: "/governance", label: "Governance", requires: "governance:read" },
  { to: "/llm-exchanges", label: "LLM Exchanges", requires: "llm:read" },
  { to: "/config", label: "Config", requires: "config:read" },
  { to: "/health", label: "Health", requires: "health:read" },
];

export const visibleNav = (permissions: string[]) => NAV.filter((n) => permissions.includes(n.requires));

/** Where "/" (and any URL the role cannot open) lands: the role's first screen in nav order. */
export const landingRoute = (permissions: string[]): string | null => visibleNav(permissions)[0]?.to ?? null;
