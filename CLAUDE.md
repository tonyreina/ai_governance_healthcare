# Working in this repository

## Requirements and design decisions

[REQUIREMENTS.md](REQUIREMENTS.md) records what must stay true.
[DECISIONS.md](DECISIONS.md) records why things are built the way they are, and
what was rejected. They are the project's memory. Treat them as binding.

**Before** writing code, planning, or recommending a design, read the entries
that touch the area. Anything marked **Active** (requirements) or **Accepted**
(decisions) is a constraint on new code unless the user says otherwise.

- **If a task would conflict with an entry, say so before building it.** Name the
  entry (R-nn, D-nn), say what would change, and let the user decide. Do not
  deviate silently, and do not quietly follow the old rule when the user has
  clearly asked for something else.
- **If the user overrides or changes one, do what they ask and record it** in the
  same change. They are the owner.
- **Keep both files current as part of the change that alters them.** New
  constraint: add the next unused `R-nn`. New design choice: add a `D-nn` with
  the reason and the alternatives rejected. Changed mind: add a new entry that
  supersedes the old one and mark the old one `Superseded by D-nn`. Never
  renumber, reuse an ID, edit history or delete an entry. Fixed a known
  violation: update its "Known violation" and "Enforced by" lines.
- **Record what the user decided, not what you assume.** Only the owner moves a
  decision from **Proposed** to **Accepted**, and an **Open** question stays
  open until they answer it. Do not write documentation, UI copy or code that
  assumes an answer to an open one (R-21 and R-22 today).
- **Cite sources.** Every entry names where it came from (a file, an issue
  number, or the user's instruction) and what enforces it. "Enforced by:
  Nothing" is honest, and is a gap to report, not hide.
- Record only what constrains future work. A passing implementation detail is not
  a decision.
- If you notice documentation or code that contradicts an entry, flag it, even
  when it is not the task at hand. That is how the claim-versus-reality bugs in
  this repository (#31, #55, #56) were found.

## Tests ship with the code

**Whenever you add or change code, add or update unit and integration tests in
the same change.** Not after, not as a follow-up. A change with no test is not
finished, and "I could not test it" is a finding to report, not a reason to skip.

Why this is a rule here: the CI that was supposed to protect this repository ran
the linters and no tests at all (#32), so twenty-four test files, including every
regression test for a closed security finding, ran only when somebody
remembered. A fix without a test is a fix that can silently stop being true, and
nothing here would say so.

- **New behavior:** a test that fails without it and passes with it.
- **Changed behavior:** update the tests that described the old behavior. Do not
  weaken or delete an assertion to make a change pass; if an assertion is wrong,
  say why in the change.
- **A bug fix:** write the regression test first and watch it fail for the right
  reason, then fix. #55 did this: the test failed with `Mode is not defined`
  before the fix and passed after, and it reads the label the user actually sees.
- **A guardrail or a check:** show it failing. A check that is never shown to
  fail is a claim, not a control, so give it mutation tests that break something
  and demand it notice (see `tests/test_workflows.py`).

### Unit and integration

- **Unit:** logic with no I/O, run anywhere: merge semantics, header parsing, the
  enum checker, the CI configuration itself. Fast, and always run.
- **Integration:** the real thing at a boundary. The API against a real
  PostgreSQL, the dashboard in a real browser, the proxy as a real Caddy, the
  whole Compose stack. Never a fake for the thing under test: a fake would test
  the fake. The database tests exist because what they test *is* the database's
  behavior (a row lock, a trigger refusing an UPDATE).
- A change that crosses a boundary needs an integration test, not just a unit
  test. The merge rule is unit-tested and also run against Postgres; the
  identity handoff cannot be tested without a real Caddy, which is exactly how
  it broke for months (#23).

### Where tests go, and how they run

| What | Where | Runs as |
|---|---|---|
| API, database, SSE | `server/tests/` (pytest) | `cd server && pytest`, needs `TEST_DATABASE_URL` |
| Dashboard, exports | `tests/test_*.py` (Playwright) | `pixi run test-<name>` |
| Proxy, Compose stack | `tests/test_proxy_identity.py`, `tests/test_stack.py` | needs Docker |
| CI configuration | `tests/test_workflows.py` | `pixi run test-workflows` |

A new test file gets a `test-*` pixi task, and that task must be run by
`.github/workflows/test.yml`. `test_workflows.py` fails if either is missing, so
a test cannot be added and quietly left out of CI.

### A skip is a failure

CI sets `REQUIRE_TESTS=1`, which turns every suite that cannot run (no database,
no Docker, no `node`, no stack) into a failure, because a skip exits 0 and reads
as a pass. Without it, 106 of the 201 server tests skip silently on a machine with
no database and the run is green. Never add a `skip`, `skipif` or
`continue-on-error` to get a check green. If a new test can skip, it must also
honor `REQUIRE_TESTS`.

### Before you say it is done

Run the tests that cover what you touched, and the ones that could have broken,
and say what you ran. Report a failure as a failure. If a suite needs something
you do not have (Docker, a database), say that it was not run rather than
implying it passed. CI will run all of them; do not use that as a reason not to
run them first.

`main` is protected: a pull request cannot merge until `tests passed`, and nobody
can bypass it. If a check is red, fix the cause. Do not try `gh pr merge --admin`,
and do not weaken or skip a check to get green (see "A skip is a failure").

### Where a test is not needed

Say so in the change, with the reason: a documentation-only edit, a generated
file (`docs/app/index.html` is rebuilt by `pixi run build-app`, which a hook
checks), a comment, a rename with no behavior change that existing tests already
cover. If the user tells you to skip tests for a change, do, and record it.

## Security claims name their evidence

[docs/security-claims.md](docs/security-claims.md) lists every security property
this project asserts, where it asserts it (the sentence is quoted), and the test
that enforces it. `pixi run check-claims` fails if a quote is no longer in the
file it cites, or if the evidence does not exist or is something CI never runs.

This is the rule that would have caught #31, #55, #56, #61 and #62: each was a
sentence in the docs or the UI claiming something no test checked, and each was
false.

- **A new sentence that asserts a security property gets a row in the same
  change**, with a test that enforces it. That includes docs, UI text, labels,
  banners and the headline comments of `compose.yaml` and the `Caddyfile`.
- **No test? Write the test, soften the sentence, or list it honestly** as
  `unenforced` with the reason. Never leave a claim sounding enforced when it is
  not.
- **When you edit a quoted sentence, the check fails until the row matches.**
  That is the point. Update the row, and ask whether the claim is still true.
- **Statuses are honest, not aspirational.** `violated` means the sentence is not
  true today; it stays in the inventory with its issue. Do not delete a row to
  make the check pass, and do not mark a claim `enforced` on a test that does not
  assert it.
- Evidence must be something CI runs: a `server/tests` test, a `tests/` suite with
  a pixi task in `test.yml`, or a pre-commit hook. A Makefile target or a manual
  step does not count.

## American English

Write American English everywhere: prose, code comments, docstrings, commit
messages, documentation and UI copy. Never British spellings.

Check before writing, not after. The slip is easiest in words that feel
neutral. Write the first, never the second:

- behavior (not behaviour) <!-- spelling-ok -->
- defense (not defence) <!-- spelling-ok -->
- organization, organize (not organisation, organise) <!-- spelling-ok -->
- license (noun and verb) (not licence) <!-- spelling-ok -->
- analyze (not analyse) <!-- spelling-ok -->
- catalog (not catalogue) <!-- spelling-ok -->
- canceled (not cancelled) <!-- spelling-ok -->
- fulfill (not fulfil) <!-- spelling-ok -->
- gray (not grey) <!-- spelling-ok -->
- toward (not towards) <!-- spelling-ok -->
- modeling (not modelling) <!-- spelling-ok -->
- labeled (not labelled) <!-- spelling-ok -->
- center (not centre) <!-- spelling-ok -->
- acknowledgment (not acknowledgement) <!-- spelling-ok -->

Quoted material keeps its original spelling: a quotation from a source, a
third-party license text, an API field name spelled the British way. Mark such a
line `spelling-ok`, or add an entry to `.spelling-allow`.

Why: the project is US-oriented. It is built around CHAI, a US non-profit, and is
aimed at US health systems, so British spellings read as inconsistent with the
subject. The user asked for this directly (R-17).

Enforced by `pixi run check-spelling`, which runs in pre-commit and CI. It is a
word list and cannot catch every case, so the check passing does not mean you
were consistent.

## Enumerated types, not strings

**A closed set of values gets a type. Never branch on a bare string.**

This is a rule with a history. The server-backed dashboard told every user
"Saved in this browser" because `MODE` was assigned `"api"` in one file and
compared with `"shared"` in another. Nothing connected the two spellings, so the
comparison was false forever and no test, linter or reviewer noticed. A typo in
a string literal is not an error anywhere. A typo in an enum member fails the
first time the line runs, and a rename follows every use.

### What counts as a closed set

Any value that code *branches on* and that comes from a fixed list: roles
(`owner`/`writer`/`reader`), statuses (`met`/`partial`/`notmet`), modes, kinds,
verdicts, error codes, identity-header formats, event names, SQL `CHECK` lists.

It is **not** a closed set, and needs no enum: a file path, a URL, a header
*name*, prose, a regex, a key you look up in a dict, a value you only pass
through, or a value defined by someone else's protocol (an ASGI scope type, a
DOM key name, an HTTP method). Name those with a constant if they repeat;
mark a genuine protocol comparison `enum-ok: <reason>` (see below).

### Python

- Use `enum.StrEnum` (3.11+). Members *are* strings, so JSON, pydantic and
  asyncpg are unchanged and there is no wire-format change to worry about.
- **Parse once, at the boundary.** `Role(raw)` raises on an unknown value; do it
  where input enters (request body, env var, DB row) and pass members everywhere
  inside. Type fields and parameters as the enum, not `str`.
- Pydantic models: annotate the field with the enum. Not `str`, not `Literal`.
- `Literal["a", "b"]` spelled as an enum is the same problem in a type hint.
  `Literal` is only for matching a third-party signature you cannot change.
- Use `match` over members and finish with `assert_never` where the set must be
  exhaustive, so adding a member is a type error at every unhandled site.
- Compare with `is` (`role is Role.OWNER`), not `==`.
- A database column holding an enum keeps a `CHECK` constraint listing the same
  values. Add a test asserting the constraint and the enum agree, so neither can
  drift.
- `class X(str, Enum)` is flagged by ruff (UP042). Write `StrEnum`.

### JavaScript

There is no enum syntax. Use a frozen object, one definition per set:

```js
const Mode = Object.freeze({ LOCAL: "local", API: "api", SHARED: "shared" });
if (MODE === Mode.API) { ... }          // never: MODE === "api"
```

- `Mode.APi` is `undefined`, which a test catches. `"apI"` is a string, which
  nothing catches.
- Never assign a state variable a bare word (`MODE = "api"`); assign `Mode.API`.
- The app is concatenated into one file in filename order (`scripts/build_app.py`),
  so a definition must live in a file that sorts before its first use, normally
  `app/js/00-core/`.
- Give a check a name when it is asked in more than one place
  (`isServerBacked()`), rather than repeating the comparison.

### Tests

Tests are exempt from the checker, deliberately: a test may pin a wire value on
purpose (`assert response.json()["role"] == "owner"` is the test that proves the
API did not silently rename it). Use the enum in a test when the point is the
domain logic; use the literal when the point is the wire format.

### The guardrail

`scripts/check_enums.py` enforces this in `pre-commit`/CI (`pixi run
check-enums`) and, as a Claude Code hook (`.claude/settings.json`), on every
Python/JS file you edit. When it reports a violation, **write the enum.**

It is a ratchet. `scripts/enum_baseline.json` records the existing uses of bare
strings, counted per file and per literal, so legacy code does not block work.
A new use fails; fixing an old one makes the baseline stale, which also fails,
so it only ever shrinks.

- **Never edit `enum_baseline.json` by hand** and never run
  `--update-baseline --allow-growth` to make a failure go away. Both defeat the
  point. `--allow-growth` is for a human who has decided otherwise.
- After you *remove* uses (by introducing an enum), run
  `python scripts/check_enums.py --update-baseline` to ratchet it down, and
  commit the smaller baseline.
- `enum-ok: <reason>` on the line excuses a genuine protocol value. The reason is
  mandatory; a bare `enum-ok` excuses nothing. Do not use it for a value this
  repository defines, such as a role, status or mode.
- If you are editing near an existing string-typed closed set, you do not have to
  convert it, but do not add a second use of it. Say so rather than silently
  extending the pattern.

`pixi run check-enums --report` lists what remains, by file: it is the
refactor backlog.

### What the checker cannot see

A green check is a tripwire for the common shape, not proof. It deliberately
does not flag these, because catching them would flag every dict lookup and
substring test and the guardrail would be switched off. They are exactly what a
well-meaning author writes to make the check pass, so do not:

- **Hoist the string into a constant.** `OWNER = "owner"` then `x == OWNER` is
  still a string, and `ROLES = ("owner", "writer")` then `x in ROLES` is the same.
  A named constant is right for a value defined by someone else's protocol. For
  a closed set this repository defines, the fix is the enum, not a constant.
- **Key a dispatch dict by the strings** (`{"csv": f}[kind]`). Key it by enum
  members.
- **Test with a literal on the left of `in`** (`"admin" in user.roles`), or go
  through `operator.eq`, `any(...)` or `__eq__`.
- **Assign a lowercase JavaScript state variable a bare word** (`mode = "api"`).
  Only SHOUTING_CASE state variables are caught, so this one rests on you.

The hook runs after Write, Edit, MultiEdit and Bash. After a Bash command it
checks every file git says changed, because a `sed -i` or a heredoc names no file.
