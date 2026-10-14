# UmaExtractor — Project Instructions

## Start with repository discovery

At the beginning of a substantial task:

1. Read this file and any relevant nested `CLAUDE.md` files.
2. Inspect the repository structure and Git status.
3. Identify the language, framework, package manager, application entry points, and test tooling.
4. Locate the relevant implementation and existing tests before proposing changes.
5. Check the current implementation before relying on assumptions from earlier conversations.

Use targeted searches rather than reading the entire repository by default.

Do not spend time rediscovering the project structure for every small follow-up task when the relevant information is already available in the current session.

## 3. Subagent delegation

Use specialized subagents to keep investigations isolated from the main session.

### Code investigation

Delegate small, read-only questions to `code-investigator`, using Sonnet with medium effort.

Examples:
- Locate a function or configuration setting.
- Trace a specific data flow.
- Find where affinity or inheritance calculations are implemented.
- Identify the API endpoint responsible for a feature.
- Summarize the relevant files before a larger change.

Request concise findings with file paths, line numbers, and uncertainties.

### Bug investigation

Delegate focused root-cause investigations to `bug-investigator`, using Sonnet with medium effort.

Examples:
- Trace a specific exception or incorrect result.
- Investigate a failing test.
- Determine whether a bug originates in the frontend, backend, or data layer.

The investigator must report evidence and a proposed fix without modifying files.

### Test writing

Use `test-writer`, using Sonnet with medium effort, for isolated test-writing tasks with clearly defined expected behavior.

The agent may edit test files and run relevant tests when safe.

The agent may also delete tests if it deems them not relevant anymore

Do not give multiple agents overlapping write responsibilities for the same files.

### Main-session responsibilities

Keep architectural decisions, cross-module implementation, complex optimization, and final integration in the main session.

Do not delegate a task merely because a subagent exists. Directly answer trivial questions when that is cheaper and simpler.

Before implementing a fix, assess whether the delegated findings are sufficient and consistent with the source code.

## Context and token efficiency

- Prefer targeted searches and relevant file excerpts.
- Avoid repeatedly reading entire files when only a small section matters.
- Do not load unrelated documentation, MCP tools, or project directories without a reason.
- Ask subagents for concise, actionable reports rather than full investigation transcripts.
- Avoid redundant summaries of information already present in the current context.
- Use lower-effort models for routine, bounded tasks and reserve stronger reasoning for work that benefits from it.
- Do not launch multiple subagents to answer the same question.
- Stop investigating once sufficient evidence is available.

Efficiency must not come at the expense of correctness.

## Architecture and implementation

- Follow the repository's existing conventions and established architecture.
- Prefer small, focused changes over unnecessary rewrites.
- Reuse existing utilities, types, components, and dependencies where appropriate.
- Avoid introducing abstractions that are not justified by the current requirements.
- Keep data transformations and scoring logic testable.
- Preserve existing interfaces unless the task requires a deliberate change.
- Handle errors explicitly and provide useful diagnostics.
- Avoid unrelated refactors, formatting changes, or dependency upgrades.
- Do not add dependencies without a clear benefit.
- Do not duplicate logic that already exists elsewhere in the repository.

Before implementing a larger feature, briefly establish the relevant data flow and identify which modules need to change.

## Testing and verification

Before changing code, identify the relevant existing tests and the project's supported test commands.

After making changes:

1. Run the narrowest relevant test first.
2. Run type checking or linting if configured and relevant.
3. Expand verification when the scope or risk warrants it.
4. Inspect the final diff.
5. Report exactly what was verified and what remains untested.

Never claim that a test, build, or type check passed unless it actually completed successfully.

Do not weaken existing tests to make a change appear successful.

Do not run destructive tests, migrations, deployments, or commands that modify external services without explicit authorization.

If the repository has no suitable test coverage for the changed behavior, consider adding focused regression tests.

## Data integrity and external services

- Treat imported game data and external responses as potentially incomplete or inconsistent.
- Validate input at appropriate boundaries.
- Do not silently discard unknown or unsupported values.
- Preserve identifiers and relationships needed to reconstruct a lineage.
- Avoid unnecessary network requests and repeated data downloads.
- Never expose API keys, credentials, or private environment variables.
- Do not modify production databases, remote services, or external resources without explicit authorization.

## Git and file safety

- Inspect the working tree before making changes.
- Preserve unrelated user modifications.
- Do not reset, discard, or overwrite existing user work.
- Do not commit, push, rebase, or rewrite Git history unless explicitly requested.
- Do not edit generated files when their source files should be changed instead.
- Avoid broad automated edits when a focused change will suffice.

## Completion report

For implementation tasks, finish with a concise report containing:

- What changed and why.
- The main files modified.
- Tests and checks actually executed.
- Results and any known limitations.
- Important assumptions or follow-up work.

For investigation-only tasks, provide the direct answer, supporting file paths, relevant line numbers, and uncertainties.

Do not repeat the entire investigation history or provide a long summary of unchanged code.

