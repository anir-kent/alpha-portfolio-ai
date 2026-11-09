# 11. Risks and Technical Debt

This section lists the known gaps, so a reviewer does not have to find them. The summaries preserve stable ids and severity. The linked detailed registers state what is true of the code, what could go wrong, what limits the damage today, and where the [Target / Production Roadmap](13-roadmap.md#roadmap-items) closes it. Fixing these gaps is outside the scope of this version. Most of them are accepted because the platform is a single-process demonstrator on synthetic data ([2. Architecture Constraints](02-architecture-constraints.md)), and none of them is accepted for production.

**Severity** is rated for a production deployment, not for the local demonstrator:

| Severity | Meaning |
| --- | --- |
| **High** | Blocks a production go-live, or weakens one of the top three quality goals (Auditability, Explainability, Human control / safety) |
| **Medium** | Must be closed before production. A compensating control limits the damage today |
| **Low** | Known and contained. Close it when the surrounding code next changes |

## 11.1 Risks

| ID | Risk / debt | Severity |
| --- | --- | --- |
| <a id="r-01"></a>R-01 | No SSO or MFA. | High |
| <a id="r-02"></a>R-02 | No CSRF token. | Medium |
| <a id="r-03"></a>R-03 | `Secure` cookie off by default. | High |
| <a id="r-04"></a>R-04 | A single API process | High |
| <a id="r-05"></a>R-05 | SQLite | High |
| <a id="r-06"></a>R-06 | In-process Run Step progress | Medium |
| <a id="r-07"></a>R-07 | Synthetic data | Medium |
| <a id="r-08"></a>R-08 | LLM provider dependency. | Medium |
| <a id="r-09"></a>R-09 | The audit chain has no external anchor. | High |
| <a id="r-10"></a>R-10 | Trajectory token cost and latency | Medium |

[Detailed risk register](appendices.md#e16-risk-register) contains the impact, current controls and linked roadmap mitigation for each id.

## 11.2 Technical debt

| ID | Risk / debt | Severity |
| --- | --- | --- |
| <a id="td-01"></a>TD-01 | No structured logging, metrics or tracing. | Medium |
| <a id="td-02"></a>TD-02 | No frontend test runner. | Medium |
| <a id="td-03"></a>TD-03 | An unanchored Research Tilt LLM Exchange. | Low |
| <a id="td-04"></a>TD-04 | Research Tilt Exchanges are rolled back with a failed scoring phase. | Medium |
| <a id="td-05"></a>TD-05 | Analysis Run recording commits once per Audit Event | Medium |
| <a id="td-06"></a>TD-06 | The recording key omits the model. | Low |
| <a id="td-07"></a>TD-07 | Hand-written migrations | Low |
| <a id="td-08"></a>TD-08 | Recordings are brittle to tool-result changes. | Low |

[Detailed technical debt register](appendices.md#e15-technical-debt-register) contains the impact, current controls and linked roadmap mitigation for each id.
