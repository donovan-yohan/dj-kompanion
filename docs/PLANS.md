# Plans

Execution plans for active and completed work.

## Current State

- No active plans

## Active Plans

| Plan | Created | Status |
|------|---------|--------|

## Completed Plans

| Plan | Created | Completed |
|------|---------|-----------|
| [Deferred Enrichment](exec-plans/completed/2026-02-26-deferred-enrichment.md) | 2026-02-26 | 2026-02-26 |

## Tech Debt

| Issue | Severity | Notes |
|-------|----------|-------|
| `_parse_claude_response` doesn't strip markdown code fences | Medium | Claude sometimes returns `\`\`\`json\n...\n\`\`\`` wrapper; parser rejects it as invalid JSON |
| Download fails with missing file extension | Medium | Tagger receives path without extension (`Unsupported format: .`); root cause likely in downloader |
