# 09: §7 Deployment and the Target / Production Roadmap

**What to build:** A reviewer sees how the system runs today and a concrete path to production. §7: as-is local topology (seeder, research seed, API process, Vite dev server, CI pipeline); a cloud-agnostic logical production view; an Azure reference mapping (App Service or AKS, Azure Database for PostgreSQL, Entra ID, Key Vault, LLM behind a LiteLLM gateway). The Roadmap, clearly separated from as-is sections, ties each item to the §11 risk or non-goal it closes.

**Blocked by:** 01, 08

**Status:** ready-for-agent

- [ ] As-is, logical and Azure deployment diagrams in Mermaid render under `check`
- [ ] Roadmap items each link to the §11 risk or §1 non-goal they address; §11 mitigation pointers resolve
- [ ] No roadmap content appears in as-is sections; `check` green
