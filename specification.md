# Platform Migration Plan — Next.js → Angular + FastAPI

> **Note:** This is technically a _re-platform / rewrite_ (different languages and frameworks), not a pure refactor. "Refactor" usually implies behavior-preserving changes within a stack; framing this as a migration sets the right expectations for risk and effort.

---

## 1. Project Metadata

| Field        | Value                                            |
| ------------ | ------------------------------------------------ |
| Project      | Platform Migration — Next.js → Angular + FastAPI |
| Owner        | [Solution Architect]                             |
| Version      | 0.1 (Draft)                                      |
| Status       | Draft → Review                                   |
| Stakeholders | Eng Lead, Backend Team, Frontend Team, QA        |

## 2. Executive Summary

The current application is a monolithic Next.js app (React UI + API routes in one codebase). We are re-platforming it into a decoupled architecture: an **Angular** single-page frontend and a **FastAPI** REST backend, communicating over a contract-first (OpenAPI) HTTP boundary. Scope is limited to the three existing features — user authentication, user management, and project-by-user — with behavior preserved and no new functionality added.

## 3. Objectives & Non-Goals

### Objectives

- Separate frontend and backend into independently deployable services.
- Replace Next.js API routes with a typed FastAPI service.
- Re-implement the UI in Angular with equivalent behavior.
- Establish an OpenAPI contract as the single source of truth between the two.

### Non-Goals (this round)

- No new features or UX redesign — visual/behavioral parity only.
- No database schema redesign (reuse existing tables).
- No change to the auth _model_ (same roles/permissions), only its implementation.
- No mobile / SSR / SEO concerns (Angular SPA is acceptable).

## 4. Scope

| In Scope                                          | Out of Scope                                          |
| ------------------------------------------------- | ----------------------------------------------------- |
| Auth: login, register, logout, session (**AUTH**) | Password reset / email flows (if not already present) |
| User management list & detail view (**USR**)      | Admin role editing, bulk ops                          |
| View projects by user (**PRJ**)                   | Project create/edit/delete                            |
| FastAPI backend + OpenAPI contract                | Data migration / new schema                           |
| Angular app shell, routing, guards                | Design system overhaul                                |

## 5. Current State / Baseline

Next.js app with: pages under `/pages`, API logic in `/pages/api/*`, auth via NextAuth (or JWT in cookies), direct DB access from API routes, shared TypeScript types between client and server. Known pain points: client/server coupling, hard to scale backend independently, mixed concerns in API routes.

## 6. Phased Plan

| Phase | Title                      | Duration       | Modules / Scope                                                                | Dependencies | Key Deliverables                                                           | Exit Criteria                                                        |
| ----- | -------------------------- | -------------- | ------------------------------------------------------------------------------ | ------------ | -------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **1** | Discovery & Mapping        | 3–4 days       | Inventory Next.js routes, API endpoints, data models, auth flow                | —            | Endpoint catalog, data model doc, auth flow diagram                        | All current endpoints & flows documented and agreed                  |
| **2** | Foundation & Contract      | 4–5 days       | FastAPI scaffold, Angular scaffold, OpenAPI contract, DB connection, JWT infra | P1           | Running FastAPI skeleton, Angular app shell, OpenAPI spec, auth middleware | Both stacks build & deploy to dev; contract reviewed                 |
| **3** | Auth Feature — **AUTH**    | 4–5 days       | Login, register, logout, JWT issue/verify, Angular guards & interceptor        | P2           | `/auth/*` endpoints, login/register UI, route guards                       | User can log in/out; protected routes enforced; parity with old flow |
| **4** | User Management — **USR**  | 3–4 days       | User list + detail endpoints, Angular list/detail views                        | P3           | `/users` endpoints, user list & detail screens                             | List/detail match legacy behavior; pagination/filter work            |
| **5** | Projects by User — **PRJ** | 3–4 days       | Projects-by-user endpoint, Angular project list view                           | P3, P4       | `/users/{id}/projects` endpoint, project view UI                           | Projects render correctly per user; authz enforced                   |
| **6** | Hardening & Cutover        | 4–5 days       | E2E tests, perf check, security review, deploy & switchover                    | P3–P5        | Test suite, CI/CD pipelines, runbook, cutover plan                         | All tests green; staging validated; rollback ready                   |
|       | **Total**                  | **21–27 days** |                                                                                |              |                                                                            |                                                                      |

## 7. Per-Phase Detail (example — Phase 3: AUTH)

- **Goal:** Replace NextAuth/cookie auth with FastAPI JWT + Angular guards.
- **Backend tasks:** `POST /auth/register`, `POST /auth/login` (returns access/refresh JWT), `POST /auth/logout`, token verification dependency, password hashing (bcrypt/argon2).
- **Frontend tasks:** Login & register components, `AuthService`, HTTP interceptor for token attach + refresh, `AuthGuard` on protected routes.
- **Testing:** Unit tests on token logic; E2E login → protected-route → logout.
- **Rollback:** Feature-flag the new auth; keep Next.js auth live until parity confirmed.

## 8. Risks & Mitigations

| Risk                                          | Likelihood | Impact | Mitigation                                       |
| --------------------------------------------- | ---------- | ------ | ------------------------------------------------ |
| Auth behavior subtly differs (session vs JWT) | Med        | High   | Document old flow in P1; parity test suite in P3 |
| Hidden coupling in Next.js API routes         | Med        | Med    | Endpoint catalog in P1 before any rewrite        |
| Two-stack CI/CD setup slows team              | Med        | Med    | Stand up pipelines in P2, not at cutover         |
| Scope creep ("just one more feature")         | High       | Med    | Non-goals section enforced in review             |

## 9. Testing & Validation Strategy

Contract tests against the OpenAPI spec; backend unit tests (pytest) per endpoint; Angular unit tests (Jasmine/Karma or Jest); E2E (Playwright/Cypress) covering the three user journeys; side-by-side parity check against the legacy app before cutover.

## 10. Rollback / Contingency

Run new and old stacks in parallel behind a router/feature flag; cut over feature-by-feature; each phase independently revertible since features are isolated.

## 11. Success Metrics

Behavioral parity on all 3 features (0 regressions in E2E); frontend and backend independently deployable; API fully described by OpenAPI; test coverage ≥ target on new code.
