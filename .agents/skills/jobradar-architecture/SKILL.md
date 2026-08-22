---
name: jobradar-architecture
description: Design, implement, refactor, or review Jobradar backend and frontend changes with lean SOLID and Clean Architecture boundaries. Use for substantive Jobradar feature work, module placement, API and data-flow design, JobSpy/ATS/web-search/LLM integrations, shared React components, reusable backend methods, generics, dependency direction, or any request mentioning architecture, SOLID, Clean Architecture, reuse, refactoring, or avoiding overengineering.
---

# Jobradar Architecture

Apply Clean Architecture as a dependency discipline, not as a quota of layers or classes. Preserve the current working system and choose the smallest design that isolates real change.

## Workflow

1. Read the affected code, nearby tests, `AGENTS.md`, and current dependency patterns before proposing structure.
2. State the feature's smallest useful vertical slice and the behavior that must remain unchanged.
3. Identify only the real boundaries: delivery, application orchestration, business rules, persistence, and external integrations.
4. Implement the slice with the fewest new concepts that keep dependencies pointing toward stable business behavior.
5. Run the architecture checks below before finishing.
6. Verify with focused tests, then broader lint/test/build and browser checks proportional to the change.

Do not perform a repository-wide layer rewrite unless the user explicitly requests it and the measured benefit justifies the migration cost.

## Backend Decisions

- Keep a modular monolith and organize new work by feature or business capability.
- Keep FastAPI routes thin: parse/validate, call a use case, map the response.
- Put orchestration in an explicitly named service or function. Keep pure rules independent of HTTP, SQLModel, JobSpy, ATS payloads, and LLM SDKs.
- Normalize JobSpy, ATS, web-search, and LLM results to one typed job contract before applying shared rules.
- Create a `Protocol` or abstract boundary only for a replaceable external system, two real implementations, or a necessary test seam.
- Use direct constructor or function injection. Do not add a dependency injection container.
- Prefer concrete repositories with domain-specific queries. Do not add generic CRUD repositories, base services, manager hierarchies, or an abstract Unit of Work.
- Separate API schema, persistence model, and domain object only when their validation, lifecycle, or behavior genuinely differs.
- Convert provider failures into contextual application errors at the integration boundary. Preserve the crawl rule that one provider failure must not stop unrelated sources.

## Reuse and Generics Gate

Extract shared code only when all are true:

1. At least two real call sites need the same concept, not merely similar syntax.
2. The code changes for the same reason.
3. The extracted name and contract are clearer than the duplicated code.
4. Tests can describe the shared behavior without source-specific conditionals.

Use a generic only when it applies the same algorithm to at least two real types, improves type safety, and makes call sites simpler. Reject the generic if it needs `Any`, reflection, string dispatch, many callbacks, or flags that select unrelated behavior. Prefer duplication over the wrong abstraction, then revisit after the pattern stabilizes.

## Frontend Decisions

- Keep React code feature-oriented. Keep `App` as composition glue rather than a feature implementation.
- Share design-system primitives and stable cross-feature controls. Keep domain components such as job scoring or discovery progress in their owning feature.
- Promote a component to `shared` only after two real uses expose a stable API.
- Prefer composition and explicit variants over components driven by many boolean props.
- Keep server state in one query/API layer and local interaction state near the owning component.
- Generate or derive TypeScript API types from FastAPI OpenAPI when practical; do not maintain parallel handwritten contracts without a reason.
- Treat loading, empty, error, responsive, keyboard, and focus behavior as part of the feature.
- Use the installed frontend design skill for new visual surfaces and the web app testing/browser skills for rendered validation.

## Vertical Slice Order

For a new capability, prefer this order and skip steps that add no value:

1. Define or adjust the canonical input/output contract.
2. Implement the business rule or application use case.
3. Add the smallest provider/persistence adapter needed.
4. Expose a thin API endpoint.
5. Add the owning frontend feature and reuse established UI primitives.
6. Test pure rules, provider mapping, API behavior, and the critical rendered user flow.

Avoid building all repositories, DTOs, screens, and extension points before the first end-to-end path works.

## Architecture Review Gate

Before accepting every new abstraction, answer:

- What concrete variation or external dependency does this isolate today?
- Which dependency points inward after this change?
- Can a direct function or small concrete type solve it more clearly?
- Does this reduce the number of reasons a module changes?
- Can it be removed without changing behavior if the predicted variation never arrives?

If the answers are vague, remove or postpone the abstraction.

Before accepting shared code, check that naming reflects a business or UI concept rather than a vague bucket. Reject catch-all `common`, `helpers`, `utils`, and oversized shared component modules.

## Verification

- Run focused tests during implementation.
- Run `.venv\\Scripts\\python.exe -m ruff check .` and the broadest practical pytest suite for backend changes.
- Run the repository's frontend typecheck, lint, tests, and build for frontend changes.
- Exercise at least one meaningful UI flow in the in-app browser after rendered changes; inspect console errors and desktop/mobile behavior when relevant.
- Report any environment-caused failure separately from product regressions.

In the final response, summarize the behavior delivered, the lean boundary chosen, intentionally deferred abstractions, and verification evidence.
