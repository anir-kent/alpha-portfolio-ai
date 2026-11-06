import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { ApprovalsPage } from "./ApprovalsPage";
import { AuditPage } from "./AuditPage";
import { LineagePage } from "./LineagePage";
import { ExchangesPage } from "./ExchangesPage";
import { GovernancePage } from "./GovernancePage";
import { PortfolioPage } from "./PortfolioPage";
import { QueuePage } from "./QueuePage";
import { visibleNav } from "./nav";
import { Icon, Pill, useQueue } from "./ui";
import "./index.css";

const ROLE_LABEL: Record<string, string> = {
  relationship_manager: "Relationship Manager",
  advisor: "Advisor",
  portfolio_manager: "Portfolio Manager",
  research_analyst: "Research Analyst",
  compliance_officer: "Compliance",
  investment_committee: "Investment Committee",
  auditor: "Auditor",
  platform_owner: "Platform Owner",
};
const LOGIN_ROLES = ["advisor", "relationship_manager", "compliance_officer", "investment_committee", "auditor", "platform_owner"];
const NAV_ICON: Record<string, string> = { "/queue": "queue", "/approvals": "approvals", "/audit": "audit", "/governance": "governance", "/llm-exchanges": "spark", "/config": "config", "/health": "health" };
/** Sidebar grouping only; which items appear is still decided by the server-issued permissions in nav.ts. */
const NAV_GROUPS: { label: string; routes: string[] }[] = [
  { label: "MONITORING", routes: ["/queue", "/approvals"] },
  { label: "GATEWAY", routes: ["/audit", "/governance", "/llm-exchanges"] },
  { label: "WORKSPACE", routes: ["/config", "/health"] },
];

function Login() {
  const qc = useQueryClient();
  const [username, setUsername] = useState("advisor");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/auth/login", { body: { username, password } });
      if (error) throw new Error("Invalid credentials");
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
  return (
    <div className="grid min-h-screen place-items-center p-4">
      <form className="panel w-[23rem] space-y-4 p-6" style={{ borderRadius: 28, boxShadow: "var(--shadow-pop), inset 0 1px 0 #fff" }} onSubmit={(e) => { e.preventDefault(); login.mutate(); }}>
        <div>
          <p className="eyebrow">Alpha Portfolio</p>
          <h1>Advisory workstation</h1>
          <p className="mt-1 text-ink-2">Advisor-assist. Nothing is executed from this system.</p>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Sign in as">
          {LOGIN_ROLES.map((r) => (
            <button key={r} type="button" aria-pressed={username === r} onClick={() => setUsername(r)}
              className={`pill ${username === r ? "pill-info" : "pill-mute"} cursor-pointer`}>{ROLE_LABEL[r]}</button>
          ))}
        </div>
        <label className="label">Username (a role name)
          <input className="field" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username (a role name)" />
        </label>
        <label className="label">Password
          <input className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" />
        </label>
        <button className="btn btn-primary w-full">Log in</button>
        {login.isError && <p role="alert" className="callout callout-neg">{login.error.message}</p>}
      </form>
    </div>
  );
}

/** Global strip: what the numbers are as of, and which engine produced the words. Shows only what the role may read. */
function StatusStrip({ permissions }: { permissions: string[] }) {
  const canQueue = permissions.includes("queue:read");
  const canGov = permissions.includes("governance:read");
  const queue = useQueue({ sort: "score" });
  const gov = useQuery({
    queryKey: ["governance"],
    enabled: canGov,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/governance");
      if (error || !data) throw new Error("Could not load governance data");
      return data;
    },
  });
  const card = gov.data?.model_card;
  return (
    <div className="statusbar panel" role="status" aria-label="System status">
      {canQueue && (
        <span>Market data as of <span className="mono text-ink">{queue.data?.as_of ?? "—"}</span>{queue.data?.run_id != null && <> · run <span className="mono text-ink">#{queue.data.run_id}</span></>}</span>
      )}
      {card ? (
        <span className="flex items-center gap-1.5">
          <span aria-hidden className={`size-2 rounded-full ${card.llm_mode === "live" ? "bg-pos shadow-[0_0_8px_#2fb67a]" : "bg-warn shadow-[0_0_8px_#e3a42b]"}`} />
          LLM <span className="mono text-ink">{card.model}</span>
          <Pill tone={card.llm_mode === "live" ? "pos" : "warn"} title={card.llm_mode === "live" ? "Calls go to the live endpoint" : "Replaying committed recordings; no live calls"}>{card.llm_mode}</Pill>
        </span>
      ) : canGov ? null : <span className="text-ink-3">LLM status visible to Governance roles</span>}
      <span className="ml-auto text-ink-3">Approved = cleared to act outside this system</span>
    </div>
  );
}

/** Floating, collapsible navigation capsule with grouped pill modules and glowing count alerts. */
function Capsule({ username, role, permissions, onLogout }: { username: string; role: string; permissions: string[]; onLogout: () => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const items = visibleNav(permissions);
  const queue = useQueue({ sort: "score" });
  const approvals = useQuery({
    queryKey: ["approvals"],
    enabled: permissions.includes("approvals:read"),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/approvals");
      if (error || !data) throw new Error("Could not load pending approvals");
      return data;
    },
  });
  const counts: Record<string, { n: number; tone: "neg" | "info"; hint: string } | undefined> = {
    "/queue": queue.data ? { n: queue.data.items.filter((i) => i.label === "High").length, tone: "neg", hint: "High-priority portfolios" } : undefined,
    "/approvals": approvals.data ? { n: approvals.data.items.length, tone: "info", hint: "Waiting for a decision" } : undefined,
  };
  return (
    <nav className="capsule panel" data-collapsed={collapsed} style={{ width: collapsed ? "4.9rem" : "15.5rem" }} aria-label="Main">
      <div className="flex items-center gap-2 px-1">
        <span className="grid size-9 shrink-0 place-items-center rounded-full border border-white/80 bg-gradient-to-b from-white to-[#e4e9f1] text-[1.0769rem] font-bold text-brand shadow-[0_4px_10px_-2px_rgba(31,38,135,0.25),inset_0_1px_0_#fff]">α</span>
        <span className="nav-text font-semibold tracking-tight">Alpha Portfolio</span>
        <button type="button" className="btn btn-ghost btn-sm nav-text ml-auto !px-2" onClick={() => setCollapsed(true)} aria-label="Collapse navigation"><Icon name="chevron" size={14} /></button>
      </div>
      {collapsed && <button type="button" className="btn btn-sm mx-auto !px-2" onClick={() => setCollapsed(false)} aria-label="Expand navigation"><Icon name="chevron" size={14} /></button>}

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto">
        {NAV_GROUPS.map((g) => {
          const group = items.filter((n) => g.routes.includes(n.to));
          if (group.length === 0) return null;
          return (
            <div key={g.label} className="panel nav-module" role="group" aria-label={g.label}>
              <span className="nav-module-label">{g.label}</span>
              {group.map((n) => {
                const c = counts[n.to];
                return (
                  <NavLink key={n.to} to={n.to} title={collapsed ? n.label : undefined} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
                    <Icon name={NAV_ICON[n.to] ?? "queue"} size={17} /><span className="nav-text">{n.label}</span>
                    {c && c.n > 0 && <span className={`nav-count ${c.tone === "info" ? "nav-count-info" : ""}`} title={c.hint} aria-label={`${c.n} ${c.hint}`}>{c.n}</span>}
                  </NavLink>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="panel space-y-2 p-2.5">
        <div className="nav-text px-1">
          <p className="eyebrow">Signed in as</p>
          <p className="truncate font-semibold">{username}</p>
          <Pill tone="info">{ROLE_LABEL[role] ?? role}</Pill>
        </div>
        <button className="nav-link" onClick={onLogout} title="Sign out and choose another role">
          <Icon name="lock" size={16} /><span className="nav-text">Switch role</span>
        </button>
      </div>
    </nav>
  );
}

function Shell({ username, role, permissions }: { username: string; role: string; permissions: string[] }) {
  const qc = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api.POST("/api/auth/logout"),
    onSuccess: () => {
      // Drop the previous role's cached data so the next login never sees it, then refetch the session.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
  return (
    <div className="flex min-h-screen">
      <Capsule username={username} role={role} permissions={permissions} onLogout={() => logout.mutate()} />
      <div className="flex min-w-0 flex-1 flex-col gap-3 p-3">
        <StatusStrip permissions={permissions} />
        <main className="min-w-0 flex-1 px-1">
          <Routes>
            {permissions.includes("queue:read") && <Route path="/queue" element={<QueuePage />} />}
            {permissions.includes("portfolio:read") && <Route path="/portfolios/:id" element={<PortfolioPage canDecide={permissions.includes("recommendation:decide")} />} />}
            {permissions.includes("approvals:read") && <Route path="/approvals" element={<ApprovalsPage permissions={permissions} />} />}
            {permissions.includes("audit:read") && <Route path="/audit" element={<AuditPage />} />}
            {permissions.includes("audit:read") && <Route path="/audit/recommendations/:id" element={<LineagePage canViewExchange={permissions.includes("llm:read")} />} />}
            {permissions.includes("governance:read") && <Route path="/governance" element={<GovernancePage canRunFixtures={permissions.includes("governance:run")} />} />}
            {permissions.includes("llm:read") && <Route path="/llm-exchanges" element={<ExchangesPage permissions={permissions} />} />}
            <Route path="*" element={<p className="text-ink-2">Select a section. Screens arrive in later tickets.</p>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function App() {
  const me = useQuery({
    queryKey: ["me"],
    retry: false,
    queryFn: async () => (await api.GET("/api/auth/me")).data ?? null,
  });
  if (me.isLoading) return null;
  return me.data ? <Shell {...me.data} /> : <Login />;
}

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={new QueryClient()}>
    <BrowserRouter><App /></BrowserRouter>
  </QueryClientProvider>,
);
