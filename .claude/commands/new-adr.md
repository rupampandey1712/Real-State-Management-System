---
description: Draft a new Architecture Decision Record in docs/decisions/
argument-hint: "<decision title>"
---
Create a new ADR titled: $ARGUMENTS

1. Read `docs/decisions/README.md` to find the next number, and use its template.
2. Read the related sections of `docs/design.md` and `docs/requirements.md`, and any existing ADRs this decision touches.
3. Draft `docs/decisions/NNNN-<kebab-title>.md` with Status: Proposed and today's date. Cover the context (with concrete constraints), the decision, its consequences (pros and cons), at least two alternatives considered, and a "Revisit when" condition.
4. Add a row to the index table in `docs/decisions/README.md`.
5. If it supersedes an ADR, update that ADR's status line and link the two.
6. List what in `design.md` would need to change if this ADR is accepted, but don't change it yet.
