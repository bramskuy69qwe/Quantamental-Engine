# `templates/` — runtime Jinja (read per request)

Loaded by `Jinja2Templates` in `api/helpers.py`. Every file here is
rendered **at request time**; contrast `frontend/`, which is build-time
source that never runs at runtime (see `frontend/README.md`).

After the Jinja retirement (`1afc9f8`) and the fragments slim-down
(`70f5f10`) this directory is down to the surfaces that genuinely cannot
be static or React-only:

| Path | Why it's still here |
| ---- | ------------------- |
| `v3.html` | **The React shell.** Must be runtime-rendered: it injects `active_account_id` (changes on account switch) and the `config.py` identity constants (Release-hygiene: a version bump must show without a rebuild). |
| `config.html` | React renders Add/Delete Account **disabled**, pointing here — retiring this strands account creation/deletion. |
| `admin/` (5 pages + 1 partial) | Operator diagnostics with no React twin. |
| `orders/needs_link.html` | The manual-link queue page. |
| `fragments/` (5) | The only fragments with a surviving HTML consumer: `ws_status` + `needs_link_queue` (base/needs_link htmx) and `account_list` / `account_detail` / `account_config` (config.html). Everything React reads is a `?format=json` door instead. |
| `primitives/` (3) | `status_indicator`, `card`, `empty_state` — the macros the surviving fragments import. See `primitives/README.md`. |
| `base.html` | Chrome + global CSS for the pages above. |

## Why there are two UI folders

The split is by **lifecycle**, not by "two frontends":

- `frontend/` → build-time source → emits `static/v3/`
- `templates/` → runtime Jinja
- `static/` → the committed build output actually served

## The path to one folder (not scheduled)

Collapsing to a single UI folder means retiring the rest of this
directory, which requires porting to React: (1) `/config`'s account
CRUD — including credential entry, so it needs its own gate — and (2) an
Admin surface covering the 5 `admin/*` pages. Only then can `v3.html`
become a build artifact and `templates/` disappear. Offered and
**deferred** by the operator on 2026-07-30 in favour of this sweep;
re-open by choosing the port program.
