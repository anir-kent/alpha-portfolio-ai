// Navigation is gated by server-issued permissions (from /api/auth/me); the
// server still enforces every action, this only decides what to show.
export interface NavItem { to: string; label: string; requires: string }

export const NAV: NavItem[] = [
  { to: "/queue", label: "Queue", requires: "queue:read" },
  { to: "/approvals", label: "Approvals", requires: "approvals:read" },
  { to: "/audit", label: "Audit", requires: "audit:read" },
  { to: "/governance", label: "Governance", requires: "governance:read" },
  { to: "/config", label: "Config", requires: "config:read" },
  { to: "/health", label: "Health", requires: "health:read" },
];

export const visibleNav = (permissions: string[]) =>
  NAV.filter((n) => permissions.includes(n.requires));
