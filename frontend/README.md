# `frontend/` — the React app (BUILD-TIME ONLY)

Source + toolchain for the MERIDIAN React UI. **Nothing in this directory
is read at engine runtime.** `build.mjs` compiles `src/` into
`static/v3/` (content-hashed) and vendors the runtime deps into
`static/vendor/`; the engine serves only those build outputs.

```bash
npm install     # once
npm run build   # -> static/v3/app.<hash>.js + tokens/shell.<hash>.css + manifest.json
```

| Path                | Role |
| ------------------- | ---- |
| `src/*.jsx`         | Page + primitive modules. Load order is **load-bearing** — see `JSX_ORDER` in `build.mjs` (modules share `window` globals; `app-shell.jsx` must stay last). |
| `src/tokens.css` · `src/shell.css` | Design tokens + shell chrome, emitted with the same build hash. |
| `build.mjs`         | esbuild transform + concatenation + the whole-bundle parse guardrail. One concatenated scope, so a duplicate top-level `const` is a **build failure**. |
| `DESIGN.md`         | The React design system (tokens, primitives, data-display standards). |
| `node_modules/`     | gitignored; build outputs under `static/` **are** committed. |

## Where the boundary is

The React app needs exactly **one** runtime-rendered HTML file, and it
lives in `templates/v3.html` — not here — because it injects
`active_account_id` (changes when the operator switches accounts) and the
`config.py` identity constants (Release-hygiene rule: a `PROJECT_VERSION_`
bump must show without a rebuild). Everything else the app needs is a
static build artifact.

- `frontend/` = build-time source → **never** served, never imported by Python.
- `templates/` = runtime Jinja, read per request (see `templates/README.md`).
- `static/` = the committed build output the engine actually serves.

Keep that split: don't add runtime-served files here, and don't put JSX
sources under `templates/`.
