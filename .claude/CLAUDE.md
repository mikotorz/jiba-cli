# jiba-cli Project Rules

## Model & Effort Selection

Match model and effort to task complexity:

| Task Type | Model | Effort |
|-----------|-------|--------|
| File renames, simple greps, build commands | Sonnet | low |
| General coding, small refactors, writing tests | Sonnet | medium |
| Multi-file refactors, complex debugging | Sonnet | high |
| Long autonomous agentic sessions | Opus | xhigh |
| Architecture decisions, subtle bugs, security reviews | Opus | max |

### Opus Approval Rule
- Never use Opus without explicit approval from the user
- Default to Sonnet unless the task genuinely requires Opus-level reasoning

### Plan → Execute Pattern
For hard tasks: plan with Opus (with approval), then execute each phase with Sonnet.

## Coding Standards
- Write clean, well-structured code
- Include appropriate tests
- Use type hints where applicable
- Keep functions focused and modular

## Agent skills

### Issue tracker

Issues live in GitHub Issues (github.com/mikotorz/jiba-cli). See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five canonical default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` + `docs/adr/` at the root. See `docs/agents/domain.md`.
