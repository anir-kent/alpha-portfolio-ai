# 8. Crosscutting Concepts

## 8.1 Deterministic engine ownership

_To be written in architecture-document ticket 07._

## 8.2 Audit recording

_To be written in architecture-document ticket 07._

## 8.3 LLM call shape and prompt versioning

_To be written in architecture-document ticket 07._

## 8.4 Recorded and live LLM modes

_To be written in architecture-document ticket 07._

## 8.5 SSE streaming

_To be written in architecture-document ticket 07._

## 8.6 Configuration service

_To be written in architecture-document ticket 07._

## 8.7 Idempotent migrations

_To be written in architecture-document ticket 07._

## 8.8 Authentication and authorization

_To be written in architecture-document ticket 07._ Authorization is enforced on the server only. The role × permission matrix below is generated from `app/rbac.py`.

<!-- BEGIN GENERATED: rbac-matrix -->

| Permission | `relationship_manager` | `advisor` | `portfolio_manager` | `research_analyst` | `compliance_officer` | `investment_committee` | `auditor` | `platform_owner` |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `analysis:run` | ✓ | ✓ |  |  |  |  |  |  |
| `approvals:read` |  |  |  |  | ✓ | ✓ |  |  |
| `assistant:use` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `audit:read` |  |  |  |  |  |  | ✓ |  |
| `audit:verify` |  |  |  |  |  |  | ✓ |  |
| `client:pii` |  | ✓ |  |  | ✓ |  |  |  |
| `committee:decide` |  |  |  |  |  | ✓ |  |  |
| `compliance:decide` |  |  |  |  | ✓ |  |  |  |
| `config:read` |  |  | ✓ |  | ✓ |  | ✓ | ✓ |
| `config:write` |  |  |  |  |  |  |  | ✓ |
| `governance:read` |  |  |  |  |  |  | ✓ | ✓ |
| `governance:run` |  |  |  |  |  |  | ✓ | ✓ |
| `grounding:read` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |
| `grounding:validate` | ✓ | ✓ |  |  |  |  |  |  |
| `health:read` |  |  |  |  |  |  |  | ✓ |
| `insight:approve` |  |  |  | ✓ |  |  |  |  |
| `insight:read` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |
| `llm:read` |  |  |  |  | ✓ |  | ✓ | ✓ |
| `portfolio:read` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |
| `queue:read` | ✓ | ✓ |  |  |  |  |  |  |
| `recommendation:decide` | ✓ | ✓ |  |  |  |  |  |  |
| `recommendation:read` | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  |
| `report:read` |  |  |  | ✓ |  |  |  |  |
| `report:upload` |  |  |  | ✓ |  |  |  |  |

<!-- END GENERATED: rbac-matrix -->

## 8.9 PII stance

_To be written in architecture-document ticket 07._
