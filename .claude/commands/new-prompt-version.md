---
description: Create a new version of an AI prompt and evaluate it against the baseline
argument-hint: "<prompt id> <what to change>"
---
Create a new prompt version: $ARGUMENTS

1. Read `docs/ai/prompts.md` (writing rules and change process), `docs/ai/guardrails.md`, and the current active prompt file in `services/ai/app/prompts/`.
2. Look at the latest eval report and the baseline for this prompt's suite, and find the failing cases the change should fix.
3. Copy the active file to `<id>.v<N+1>.md`. Never edit the released version. Make the change, and update the `version` and `changelog` fields in the front-matter.
4. Tell me the expected eval cost, then restart the ai service with `AI_PROMPT_VERSION_<ID>=<N+1>` and `AI_FAKE=false`, and run `python evals/run_evals.py --suite <suite>`. Compare with `evals/baselines/<suite>.json`.
5. Report the metrics against the baseline and the gates, plus any new regressions with their case IDs.
6. Only if all gates pass: update the catalog table in `docs/ai/prompts.md`. Don't switch the active version in shared config unless I confirm.
