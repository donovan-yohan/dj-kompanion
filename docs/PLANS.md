# Plans

Execution plans for active and completed work.

## Current State

- Audio post-processing feature complete (allin1 requires Docker on macOS ARM64 — deferred)

## Active Plans

_No active plans._

## Completed Plans

| Plan | Created | Completed |
|------|---------|-----------|
| [Audio Post-Processing](exec-plans/completed/2026-02-27-audio-post-processing.md) | 2026-02-27 | 2026-02-27 |
| [Download Queue](exec-plans/completed/2026-02-26-download-queue.md) | 2026-02-26 | 2026-02-27 |
| [Bugfix: JSON Fences & Missing Extension](exec-plans/completed/2026-02-26-bugfix-json-fences-and-missing-extension.md) | 2026-02-26 | 2026-02-27 |
| [Deferred Enrichment](exec-plans/completed/2026-02-26-deferred-enrichment.md) | 2026-02-26 | 2026-02-26 |

## Tech Debt

| Item | Description | Priority |
|------|-------------|----------|
| Docker container for allin1 | allin1 can't run natively on macOS ARM64 (NATTEN has no macOS wheels). Need Dockerfile + HTTP wrapper to run allin1 in Linux container. | Medium |
