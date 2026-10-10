# Bring your own framework

The dashboard is one engine that draws every screen, computes every status and
writes every export from a **definition**: a JSON file describing a framework's
sections, items, statuses, checkpoints and lifecycle. CHAI and OPTICA are two
such definitions. You can build the dashboard with your own in their place:
your organization's review process, a regulator's checklist, or an internal
policy.

The published dashboard is always CHAI with OPTICA. A build of your own
framework is a separate page, written where you say, and never replaces it.

## Try the example

`app/frameworks/example/` is a small, made-up framework ([its
checklist](example-checklist.md)): three steps, eight checks, a go-live decision
and a yearly review that can retire the tool. It is not a standard and is not
guidance. It is there to copy.

```bash
pixi run build-example          # writes build/example/index.html
```

Open `build/example/index.html` in a browser and choose **Add sample projects**.
The samples are written in the definition itself.

## Make your own

1. Copy `app/frameworks/example/` to `app/frameworks/<your-id>/`, and set
   `id` in `framework.json` to the same name.
2. Edit the definition. `schema/framework.schema.json` describes every field,
   and `pixi run check-framework` checks it: the schema, then the rules a schema
   cannot state (ids are unique, every reference exists, a lifecycle can end,
   view ids do not collide).
3. List it in a build file, as `app/frameworks/example/build.json` does:

    ```json
    { "primary": "your-id", "frameworks": ["your-id"] }
    ```

4. Build it:

    ```bash
    pixi run python scripts/build_app.py \
        --config app/frameworks/your-id/build.json --out build/your-id
    ```

`--out` writes `index.html` and `csp.caddy`, the proxy's policy for that page.
The build refuses an `--out` under `docs/` or `proxy/`, where the published page
and its policy live.

### What a definition says

| Field | What it is |
|---|---|
| `sections` | The steps of the review, each with its items |
| `categories` | The themes items are tagged with; the report scores each one |
| `statuses` | What an item can be, each with a class the engine scores by: `done`, `partial`, `open`, `declined` or `excluded` |
| `gates` | Checkpoints after a section. Each option has a class: `go`, `conditional`, `revise`, `stop` or `retire` |
| `phases` | Where a project is in its life, each reached by a `go` at a gate |
| `review` | Which gate recurs, and how often (by the project's risk tier) |
| `flags` | Which of the engine's warnings apply: past due, open items once live, an approval with no rationale, a project left idle |
| `samples` | Worked examples for **Add sample projects** |
| `keys`, `nouns` | What your sections, categories and items are called ("step", "theme", "check") |
| `ui` | Optional. Your own wording for a sentence on a screen, by catalog key; any you leave out uses the engine's neutral wording |
| `export` | Your JSON export's `schema` id and file name suffix |

A framework with no checkpoints and no phases is a plain checklist: it is scored,
but has no lifecycle column.

A **supplement** (`"role": "supplement"`) is a second framework that rides along
with the primary, as OPTICA does with CHAI. It never changes the primary's
status, score or flags (R-64).

### Translations

English is the definition itself. Any other language is optional: add
`app/frameworks/<your-id>/i18n/<language>.json` with every key your definition
implies (the example's `es.json` shows the shape). `pixi run check-i18n` fails a
language file that is missing a key, so a language you supply is complete. A
language you do not supply shows your English text, with a note on the page
saying so. The dashboard's own words (buttons, headings, the engine's neutral
sentences) are translated in every language already.

## What stays the same

- **Your words are text.** A definition's text is never run as code: it can
  hold any characters, and the dashboard shows them as text.
- **Records belong to one framework.** Every record your build makes is stamped
  with your primary's id. Your build lists, opens and imports only its own
  records; a record of another framework is left off the portfolio, with a note
  saying how many, and refused when opened or imported. A record with no stamp
  was made by the published build, and belongs to CHAI.
- **Saved work is kept apart.** In local mode, your build saves under browser
  storage keys that carry your primary's id, so it never mixes with the
  published build's work on the same machine.
- **The rest is the same code** as the published build: the change history,
  evidence references and exports work as they do there.

!!! warning "Running your build behind the server"

    The server decides when a retired project's records may be disposed of. It
    reads that from the framework's checkpoint options classed `retire`. Until
    the server carries each framework's retirement rules (#168), it knows only
    CHAI's, so run a build of your own framework in local mode.

`pixi run test-custom-build` builds the example and checks all of this in a
real browser: every screen, the report and every export, with no word of CHAI or
OPTICA in any of them.
