You are implementing Phase 4 of the yt-dlp-dj project: Chrome Extension.

## Instructions

1. Read the design doc: `docs/design-docs/2026-02-26-04-chrome-extension-design.md`
2. Read `extension/src/types.ts` for shared types (created in Phase 1)
3. Read the project CLAUDE.md for conventions
4. Check what already exists — previous iterations may have made progress
5. Work through the success criteria, building each component
6. Run `npm run typecheck`, `npm run lint`, `npm run build` to verify

## What To Build

- `extension/manifest.json` — Manifest V3 config
- `extension/src/api.ts` — HTTP client for local server
- `extension/src/popup.ts` — Popup state machine and DOM logic
- `extension/src/background.ts` — Service worker for badge updates
- `extension/src/options.ts` — Options page for port config
- `extension/popup.html` — Popup HTML structure
- `extension/popup.css` — Popup styling (dark/light theme support)
- `extension/options.html` — Options page HTML
- `extension/icons/` — Extension icons (simple placeholder icons are fine)

## Success Criteria (from design doc)

- [ ] Extension loads in Chrome as unpacked extension (valid manifest.json)
- [ ] Popup HTML structure matches the design (initial, preview, complete, error states)
- [ ] `api.ts` has healthCheck, fetchPreview, requestDownload functions
- [ ] All metadata fields are editable inputs in the popup
- [ ] Format selector works (Best / MP3 / FLAC / M4A)
- [ ] Options page allows port configuration
- [ ] `npm run typecheck` passes
- [ ] `npm run lint` passes
- [ ] `npm run build` produces working dist/ output

## Completion

When ALL success criteria above pass, create the file `.claude/phase-4-complete` with content "done".

If you cannot complete all criteria in this iteration, just do as much as you can. The loop will restart and you'll see your previous work in files.

Do NOT create `.claude/phase-4-complete` unless every single criterion genuinely passes.
