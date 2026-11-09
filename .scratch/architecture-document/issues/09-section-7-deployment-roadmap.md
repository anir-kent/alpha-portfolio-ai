# 09: §7 Deployment and the Target / Production Roadmap

**What to build:** A reviewer sees how the system runs today and a concrete path to production. §7: as-is local topology (seeder, research seed, API process, Vite dev server, CI pipeline); a cloud-agnostic logical production view; an Azure reference mapping (App Service or AKS, Azure Database for PostgreSQL, Entra ID, Key Vault, LLM behind a LiteLLM gateway). The Roadmap, clearly separated from as-is sections, ties each item to the §11 risk or non-goal it closes.

**Blocked by:** 01, 08

**Status:** resolved

- [x] As-is, logical and Azure deployment diagrams in Mermaid render under `check`
- [x] Roadmap items each link to the §11 risk or §1 non-goal they address; §11 mitigation pointers resolve
- [x] No roadmap content appears in as-is sections; `check` green

## Comments

**2026-11-08, implementation (Codex).**
- §7 documents the local seeder, Research seed, single API process, Vite proxy, data files, recorded/live LLM boundary and three CI jobs, with an as-is Mermaid topology.
- The logical production and Azure reference diagrams live in the Roadmap, linked from §7's required headings. This preserves the spec's rule that sections 1–12 describe implemented behavior only. Azure maps compute to App Service (AKS alternative), PostgreSQL, Entra ID, Key Vault and a private LiteLLM gateway.
- Ten roadmap items name proposed owners, dependencies and exit evidence. All 18 §11 risk/debt mitigation links point to specific items, each of which links back. Performance/scalability non-goals link to their actual location, §10.3; §1's no-execution boundary stays in force.
- Independent Standards and Spec reviews: zero findings on both axes.
- Verified: architecture document `check` including Mermaid is OK; architecture tests: 18 passed; full suite: 739 passed, 1 skipped (10 deprecation warnings); mypy: 112 source files clean; Ruff lint/format clean; frontend lint (39 existing Fast Refresh warnings), format and type checks pass.
