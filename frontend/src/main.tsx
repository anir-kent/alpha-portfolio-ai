import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { ApprovalsPage } from "./ApprovalsPage";
import { AuditPage } from "./AuditPage";
import { GovernancePage } from "./GovernancePage";
import { PortfolioPage } from "./PortfolioPage";
import { QueuePage } from "./QueuePage";
import { visibleNav } from "./nav";
import "./index.css";

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
    <form className="mx-auto mt-24 flex w-80 flex-col gap-3" onSubmit={(e) => { e.preventDefault(); login.mutate(); }}>
      <h1 className="text-xl font-semibold">Sign in</h1>
      <input className="rounded border p-2" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username (a role name)" />
      <input className="rounded border p-2" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" />
      <button className="rounded bg-slate-800 p-2 text-white">Log in</button>
      {login.isError && <p className="text-sm text-red-600">{login.error.message}</p>}
    </form>
  );
}

function Shell({ username, role, permissions }: { username: string; role: string; permissions: string[] }) {
  const qc = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api.POST("/api/auth/logout"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
  const items = visibleNav(permissions);
  return (
    <div className="flex min-h-screen">
      <nav className="w-52 space-y-1 bg-slate-900 p-4 text-slate-100" aria-label="Main">
        <p className="mb-4 text-sm">{username}<br /><span className="text-slate-400">{role}</span></p>
        {items.map((n) => (
          <NavLink key={n.to} to={n.to} className="block rounded px-2 py-1 hover:bg-slate-700">{n.label}</NavLink>
        ))}
        <button className="mt-6 text-sm text-slate-400 underline" onClick={() => logout.mutate()}>Log out</button>
      </nav>
      <main className="flex-1 p-6">
        <Routes>
          {permissions.includes("queue:read") && <Route path="/queue" element={<QueuePage />} />}
          {permissions.includes("portfolio:read") && <Route path="/portfolios/:id" element={<PortfolioPage canDecide={permissions.includes("recommendation:decide")} />} />}
          {permissions.includes("approvals:read") && <Route path="/approvals" element={<ApprovalsPage permissions={permissions} />} />}
          {permissions.includes("audit:read") && <Route path="/audit" element={<AuditPage />} />}
          {permissions.includes("governance:read") && <Route path="/governance" element={<GovernancePage canRunFixtures={permissions.includes("governance:run")} />} />}
          <Route path="*" element={<p className="text-slate-600">Select a section. Screens arrive in later tickets.</p>} />
        </Routes>
      </main>
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
