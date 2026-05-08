# Bearings frontend (SvelteKit)

The v1 SvelteKit + Tailwind + shiki + marked frontend. Scaffolded by
**item 2.1 — SvelteKit scaffolding + app shell** per
`~/.claude/plans/bearings-v1-rebuild.md`.

## Layout

- `src/routes/+layout.svelte` — three-column app shell
  (sidebar / main conversation / inspector) per
  `docs/behavior/chat.md`.
- `src/routes/+page.svelte` — empty-state landing route. Item 2.2's
  sidebar will navigate to `/sessions/<id>` and render real
  conversations in the same slot.
- `src/lib/render.ts` — markdown + syntax-highlight primitives
  (`marked` + `shiki`). Item 2.3 hooks them into live message bubbles.
- `src/lib/{api,stores,components/*,context-menu,keyboard,actions,themes,utils}/`
  — feature-grouped directories per `docs/architecture-v1.md` §1.2,
  populated by items 2.2-2.10.
- `src/app.html` / `src/app.css` — root document + theme tokens
  (Midnight Glass / Default / Paper Light per
  `docs/behavior/themes.md`). Item 2.9 wires the live picker.

## Build pipeline

The static adapter writes the bundle to `../src/bearings/web/dist/`
so it ships inside the Python wheel and the FastAPI app's
`bearings.web.static.mount_static_bundle` hook serves it directly.

| Script                                  | Purpose                                                   |
| --------------------------------------- | --------------------------------------------------------- |
| `npm run dev`                           | Vite dev server with API/WS proxy → FastAPI on port 8788. |
| `npm run build`                         | Static SPA build → `../src/bearings/web/dist/`.           |
| `npm run preview`                       | Preview the production build locally.                     |
| `npm run check`                         | `svelte-check` strict-typecheck.                          |
| `npm run test`                          | Vitest unit tests (jsdom + @testing-library/svelte).      |
| `npm run lint`                          | ESLint flat-config.                                       |
| `npm run format:check` / `format:write` | Prettier.                                                 |
| `npm run knip`                          | Dead-export + unused-dep check.                           |
| `npm run depcheck`                      | Unused npm dep check.                                     |

The pre-commit hooks at the repo root run all of the above on
`frontend/**` changes.
