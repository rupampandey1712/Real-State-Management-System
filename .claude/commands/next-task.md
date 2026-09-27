---
description: Pick up and implement the next task from docs/tasks.md using the spec-driven workflow
argument-hint: "[optional task ID, e.g. T1.4]"
---
Implement a task from `docs/tasks.md` following CLAUDE.md §3.

Task: $ARGUMENTS (if empty, choose the first unchecked task in the earliest phase whose dependencies are all `[x]`).

Steps:
1. Read the task entry, then read every requirement (FR/NFR) and design section (§) it references, and any ADRs or `docs/ai/*` files that apply.
2. Check the current code for anything that already exists for this task.
3. Reply with a short plan: files to create/modify, tests to add, docs to update, open questions. If a spec is ambiguous or contradicts the code, stop and ask.
4. Mark the task `[~]` in `docs/tasks.md`, then implement it in small steps, writing tests alongside the code.
5. Run the relevant lint, typecheck and test commands from CLAUDE.md §5, and fix failures. For tasks marked 🤖, also run the matching eval suite if the feature is runnable (tell me the expected cost first).
6. Check the task's "Done when" criteria one by one and report each as met or not met.
7. Mark the task `[x]` only if every criterion is met. Update design.md or add an ADR if the design changed. Put out-of-scope ideas in the Parking lot.
8. Summarise the files changed, the test results, and anything left undone.
