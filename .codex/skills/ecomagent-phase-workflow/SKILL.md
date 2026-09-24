---
name: ecomagent-phase-workflow
description: Develop one explicitly requested EcomAgent phase with minimal context, focused tests, teaching-oriented code, secure API handling, and a single end-of-phase report. Use for implementation, testing, or completion work on an EcomAgent development phase; do not use for unrelated repository tasks.
---

# EcomAgent Phase Workflow

Develop only the Phase explicitly requested by the user. Do not implement, scaffold, or prepare later Phases. Stop after the current Phase is complete and wait for user acceptance.

## Start with minimal context

1. Read the repository `AGENTS.md` first and follow it together with the user's current request.
2. Inspect Git status, then read only the core files directly needed for the current Phase. Use targeted searches instead of scanning the whole repository.
3. Treat prior Phase modules that are stable and passing as boundaries. Modify them only when the current requirement genuinely needs a change, and explain why.
4. Reuse already-read, unchanged information. Do not reread large files, repeat repository exploration, or browse the network unless current implementation uncertainty requires it.

## Implement the smallest clear solution

- Prefer the simplest design that satisfies the current Phase and is easy for a learner to explain.
- Reuse the existing Service, Tool, and Agent layers. Keep business calculations in their owning layer rather than duplicating them.
- Make the smallest relevant file changes. Do not perform unrelated cleanup or refactoring merely for elegance.
- Add a dependency or framework only when the current Phase needs it. Explain what problem the technology solves and why it is needed now.
- Do not proactively introduce LangGraph, MCP, Multi-Agent, Redis, Docker, microservices, or other out-of-scope infrastructure unless the user explicitly requests it.
- Favor clear responsibilities and readable code over clever abstractions or advanced techniques used only for display.

## Test efficiently

1. During development, run targeted tests for the changed behavior.
2. After targeted tests pass, run the full offline test suite once for final regression verification. Repeat it only after subsequent changes that can affect results.
3. Test LLM behavior offline with a clearly labeled fake or mock model wherever possible. Never present fake-model results as real model validation.
4. Use the real Qwen API only for the minimum final acceptance needed by the current Phase. Avoid repeated live calls and preserve the configured provider and model unless the user directs otherwise.
5. Do not change production business logic merely to make a test convenient.

## Protect secrets

- Store API keys only in local `.env` files or environment variables.
- Never put real keys in source, tests, README files, logs, reports, generated tracked artifacts, or any Git-tracked file.
- Before recommending a Commit, inspect Git status and diff and run the project's secret check. Confirm `.env` remains ignored and untracked.

## Report once at Phase completion

Create one `Phase` report after implementation and verification. Base every statement on actual code and observed results; do not invent bugs, difficulties, optimizations, or capabilities. Include:

- Phase goal and functions actually completed;
- important added or modified files and their roles;
- data flow or call flow;
- new technology, the problem it solves, and why this Phase needs it;
- real issues encountered, with cause, investigation, and resolution, or an explicit statement that none occurred;
- targeted, full offline, and any necessary live-test results, clearly distinguished;
- current limitations and the boundary of the next Phase;
- three to five understanding or interview questions, followed by a separate reference-answer section;
- `我现在应该重点看哪些代码`: two to five files or functions in reading order, with what to understand in each;
- Git change summary and one suggested Commit message.

Do not repeatedly summarize intermediate edits or rescan the entire project merely to write the report. Keep notes from the actual work and report once.

## Stop at the Phase boundary

- Do not Commit automatically.
- Do not start the next Phase automatically.
- Present the completed Phase and wait for user acceptance and explicit Commit authorization.
