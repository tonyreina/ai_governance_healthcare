#!/usr/bin/env python3
"""Unit tests for the CI configuration itself.

CI once ran the linters and no tests at all (#32): twenty-four test files, every
regression test for a closed security finding among them, ran only when someone
remembered. That is a failure of configuration, and configuration can be tested.

What is asserted, and why each one earns its place:

* every `pixi run test-*` task is run by .github/workflows/test.yml. A test added
  later cannot be silently left out of CI, which is how the gap opened;
* every tests/test_*.py file is reachable from a pixi task, so a test cannot be
  orphaned either;
* REQUIRE_TESTS is set, so a suite that cannot run fails instead of skipping
  (a skip exits 0 and reads as a pass), in test.yml and in every workflow that
  runs the prek hooks (check-app among them skips `node --check` without node);
* nothing may `continue-on-error`, and every job has a timeout;
* the Postgres in CI is the major version compose.yaml pins;
* one aggregate job depends on all the others, so branch protection can require a
  single name and a new job cannot be forgotten;
* the slow jobs split to run side by side (D-97) still run everything, once: each
  leg of the server matrix runs its own pytest (and only the restricted-role leg
  sets TEST_APP_ROLE), the proxy-mcp matrix holds every shard 1..n and tells each
  which it is, and the Chromium suites dealt into browser-* jobs run once each,
  after Chromium is installed, and even after an earlier suite failed.

Each rule has a mutation test: break a copy of the real workflow and demand the
rule notice. A check that is never shown to fail is a claim, not a control.

    pixi run test-workflows
"""

from __future__ import annotations

import copy
import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
TEST_WORKFLOW = WORKFLOWS / "test.yml"
LINT_WORKFLOW = WORKFLOWS / "lint.yml"

TEST_TASK_PREFIX = "test-"
REQUIRE_VAR = "REQUIRE_TESTS"
AGGREGATE_JOB = "tests-passed"
SERVER_JOB = "server"
POSTGRES_SERVICE = "postgres"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# --- loading ----------------------------------------------------------------


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    """The `on:` block. YAML 1.1 reads the bare key `on` as the boolean True."""
    return workflow.get("on") or workflow.get(True) or {}


def jobs(workflow: dict) -> dict:
    return workflow.get("jobs") or {}


def run_commands(workflow: dict) -> list[str]:
    return [
        step["run"]
        for job in jobs(workflow).values()
        for step in job.get("steps", [])
        if "run" in step
    ]


def pixi_tasks() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pixi.toml").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for name, value in data.get("tasks", {}).items():
        out[name] = value if isinstance(value, str) else str(value.get("cmd", ""))
    return out


def test_files() -> list[str]:
    return sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))


# --- the rules --------------------------------------------------------------
# Each takes plain data and returns a list of problems, so the mutation tests can
# hand it a deliberately broken copy.


def untested_tasks(workflow: dict, tasks: dict[str, str]) -> list[str]:
    commands = "\n".join(run_commands(workflow))
    wanted = [t for t in tasks if t.startswith(TEST_TASK_PREFIX)]
    return [
        f"pixi task {t!r} is never run by CI"
        for t in wanted
        if not re.search(rf"pixi run {re.escape(t)}\b", commands)
    ]


def orphan_tests(tasks: dict[str, str], files: list[str]) -> list[str]:
    commands = "\n".join(tasks.values())
    return [f"{f} is not run by any pixi task" for f in files if f not in commands]


def no_server_pytest(workflow: dict) -> list[str]:
    server = jobs(workflow).get(SERVER_JOB, {})
    ran = any(
        "pytest" in step.get("run", "") and step.get("working-directory") == "server"
        for step in server.get("steps", [])
    )
    return [] if ran else ["the server job does not run pytest from server/"]


def no_mcp_pytest(workflow: dict) -> list[str]:
    """The MCP service's own pytest (mcp/tests, #164) runs in the server job, against
    the same PostgreSQL, with its package installed."""
    steps = jobs(workflow).get(SERVER_JOB, {}).get("steps", [])
    problems = []
    if not any(
        "pytest" in step.get("run", "") and step.get("working-directory") == "mcp"
        for step in steps
    ):
        problems.append("the server job does not run pytest from mcp/")
    if not any(
        "pip install" in s.get("run", "") and "mcp[dev]" in s["run"] for s in steps
    ):
        problems.append("the server job does not install the MCP service's package")
    return problems


def stack_suite_order(workflow: dict) -> list[str]:
    """In the stack job the MCP suite runs before the end-to-end one, the order proved
    by running both (each suite also clears the source's failure allowance it spends,
    so neither depends on the other's leftovers). The order is pinned so a change to it
    is a decision, and is proved again (#164 review H2)."""
    runs = [s.get("run", "") for s in jobs(workflow).get("stack", {}).get("steps", [])]
    at = {
        name: next(
            (i for i, r in enumerate(runs) if f"pixi run {name}" == r.strip()), -1
        )
        for name in ("test-stack-mcp", "test-stack")
    }
    if min(at.values()) < 0:
        return ["the stack job does not run both test-stack-mcp and test-stack"]
    if at["test-stack-mcp"] > at["test-stack"]:
        return ["test-stack-mcp runs after test-stack: the order proved is MCP first"]
    return []


def skips_allowed(workflow: dict) -> list[str]:
    value = str((workflow.get("env") or {}).get(REQUIRE_VAR, ""))
    return (
        []
        if value not in ("", "0", "false")
        else [
            f"{REQUIRE_VAR} is not set at workflow level: a skip would read as a pass"
        ]
    )


def hooks_may_skip(workflows: dict[str, dict]) -> list[str]:
    """Every workflow that runs the prek hooks sets REQUIRE_TESTS: a hook that
    cannot do part of its work (check-app without node) then fails, not skips."""
    return [
        f"{name} runs prek but {problem}"
        for name, wf in workflows.items()
        if any("prek run" in cmd for cmd in run_commands(wf))
        for problem in skips_allowed(wf)
    ]


def swallowed_failures(workflow: dict) -> list[str]:
    problems = []
    for name, job in jobs(workflow).items():
        if job.get("continue-on-error"):
            problems.append(f"job {name!r} has continue-on-error")
        for step in job.get("steps", []):
            if step.get("continue-on-error"):
                problems.append(f"a step in {name!r} has continue-on-error")
    return problems


def missing_timeouts(workflow: dict) -> list[str]:
    return [
        f"job {name!r} has no timeout-minutes"
        for name, job in jobs(workflow).items()
        if "timeout-minutes" not in job
    ]


def postgres_drift(workflow: dict, compose: dict) -> list[str]:
    ci = (
        jobs(workflow)
        .get(SERVER_JOB, {})
        .get("services", {})
        .get(POSTGRES_SERVICE, {})
        .get("image")
    )
    pinned = compose.get("services", {}).get("db", {}).get("image")
    if ci == pinned and ci:
        return []
    return [f"CI tests against {ci!r} but compose.yaml pins {pinned!r}"]


def aggregate_problems(workflow: dict) -> list[str]:
    job = jobs(workflow).get(AGGREGATE_JOB)
    if job is None:
        return [f"there is no {AGGREGATE_JOB!r} aggregate job"]
    problems = []
    others = set(jobs(workflow)) - {AGGREGATE_JOB}
    needs = set(job.get("needs", []))
    if others - needs:
        problems.append(f"{AGGREGATE_JOB} does not depend on {sorted(others - needs)}")
    if "always()" not in str(job.get("if", "")):
        problems.append(
            f"{AGGREGATE_JOB} would be skipped, not failed, when a job fails"
        )
    conditions = " ".join(str(s.get("if", "")) for s in job.get("steps", []))
    if "skipped" not in conditions:
        problems.append(f"{AGGREGATE_JOB} treats a skipped job as a pass")
    return problems


def trigger_problems(workflow: dict) -> list[str]:
    on = triggers(workflow)
    problems = []
    if "pull_request" not in on:
        problems.append("tests do not run on pull_request")
    if "main" not in (on.get("push") or {}).get("branches", []):
        problems.append("tests do not run on push to main")
    return problems


def permission_problems(workflow: dict) -> list[str]:
    permissions = workflow.get("permissions")
    if permissions is None:
        return ["no top-level permissions block (the default is broad)"]
    writes = [k for k, v in permissions.items() if v != "read"]
    return [f"test workflow requests {k}: {permissions[k]}" for k in writes]


def actionlint_missing(workflow: dict) -> list[str]:
    return (
        []
        if "actionlint" in "\n".join(run_commands(workflow))
        else ["the workflows are not statically analyzed (actionlint)"]
    )


ENGINES_JOB = "engines"
ENGINE_SUITES = (
    "pixi run test-csp",
    "pixi run test-injection",
    "pixi run test-markdown-render",
)
OTHER_ENGINES = {"firefox", "webkit"}


def engine_problems(workflow: dict) -> list[str]:
    """The page policy and the injection suite run in Firefox and WebKit (#160)."""
    job = jobs(workflow).get(ENGINES_JOB)
    if job is None:
        return [f"there is no {ENGINES_JOB!r} job, so only Chromium is tested"]
    problems = []
    matrix = set(job.get("strategy", {}).get("matrix", {}).get("engine", []))
    if matrix != OTHER_ENGINES:
        problems.append(
            f"{ENGINES_JOB} runs {sorted(matrix)}, not {sorted(OTHER_ENGINES)}"
        )
    if "matrix.engine" not in str(job.get("env", {}).get("TEST_BROWSER", "")):
        problems.append(f"{ENGINES_JOB} does not pass the engine as TEST_BROWSER")
    runs = " ".join(str(s.get("run", "")) for s in job.get("steps", []))
    problems += [
        f"{ENGINES_JOB} does not run `{suite}`"
        for suite in ENGINE_SUITES
        if suite not in runs
    ]
    if "playwright install" not in runs or "matrix.engine" not in runs:
        problems.append(f"{ENGINES_JOB} does not install the engine it tests")
    return problems


# --- the split jobs (D-97) ---------------------------------------------------
# The slow jobs run in pieces side by side. A piece that quietly runs nothing is
# green, so each split is checked for running everything, once.

# Each leg of the server matrix and the directory its pytest runs from.
SERVER_LEGS = {"owner": "server", "app-role": "server", "mcp": "mcp"}
APP_ROLE_LEG = "app-role"
APP_ROLE_VAR = "TEST_APP_ROLE"
LEG_CONDITION = re.compile(r"^\$\{\{\s*matrix\.suite == '([^']*)'\s*\}\}$")


def server_matrix_problems(workflow: dict) -> list[str]:
    """The server job is a matrix of its three pytest runs. Each leg runs its own
    suite exactly once, from the right directory, and only the restricted-role leg
    connects as the restricted role."""
    job = jobs(workflow).get(SERVER_JOB, {})
    strategy = job.get("strategy") or {}
    legs = list((strategy.get("matrix") or {}).get("suite") or [])
    problems = []
    if sorted(legs) != sorted(SERVER_LEGS):
        problems.append(f"the server matrix is {legs}, not {sorted(SERVER_LEGS)}")
    if strategy.get("fail-fast", True) is not False:
        problems.append("the server matrix cancels the other legs when one fails")
    if APP_ROLE_VAR in (job.get("env") or {}):
        problems.append(f"{APP_ROLE_VAR} is set for every leg of the server job")

    by_leg: dict[str, list[dict]] = {leg: [] for leg in SERVER_LEGS}
    for step in job.get("steps", []):
        run = step.get("run", "")
        found = LEG_CONDITION.match(str(step.get("if", "")))
        leg = found[1] if found else None
        if "pytest" in run:
            if leg is None:
                problems.append(
                    f"a pytest step is not tied to one leg: {step.get('if')!r}"
                )
            elif leg not in legs:
                problems.append(
                    f"a pytest step runs in leg {leg!r}, which does not exist"
                )
            else:
                by_leg[leg].append(step)
        elif "mcp[dev]" in run and leg not in (None, "mcp"):
            problems.append("the MCP service's package is not installed in the mcp leg")
        if APP_ROLE_VAR in (step.get("env") or {}) and leg != APP_ROLE_LEG:
            problems.append(
                f"{APP_ROLE_VAR} is set on a step outside the {APP_ROLE_LEG} leg"
            )

    for leg, directory in SERVER_LEGS.items():
        steps = by_leg[leg]
        if len(steps) != 1:
            problems.append(f"the {leg} leg runs {len(steps)} pytest steps, not 1")
            continue
        if steps[0].get("working-directory") != directory:
            problems.append(f"the {leg} leg does not run pytest from {directory}/")
        role = str((steps[0].get("env") or {}).get(APP_ROLE_VAR, ""))
        if (leg == APP_ROLE_LEG) != (role == "1"):
            problems.append(
                f"the {leg} leg {'sets' if role == '1' else 'lacks'} {APP_ROLE_VAR}=1"
            )
    return problems


PROXY_MCP_JOB = "proxy-mcp"
SHARD_VAR = "MUTANT_SHARD"
SHARD_VALUE = "${{ matrix.shard }}/${{ strategy.job-total }}"


def proxy_mcp_shard_problems(workflow: dict) -> list[str]:
    """proxy-mcp is a matrix of shards 1..n, each told it is shard i of n. The test
    deals mutant k to shard k % n + 1 (test-mutant-shards proves that partitions the
    list), so the matrix must hold every shard from 1 to n: one missing is a fifth of
    the mutants never run."""
    job = jobs(workflow).get(PROXY_MCP_JOB)
    if job is None:
        return [f"there is no {PROXY_MCP_JOB!r} job"]
    strategy = job.get("strategy") or {}
    shards = list((strategy.get("matrix") or {}).get("shard") or [])
    env = job.get("env") or {}
    problems = []
    if not shards or shards != list(range(1, len(shards) + 1)):
        problems.append(f"the {PROXY_MCP_JOB} shards are {shards}, not 1..n")
    if str(env.get(SHARD_VAR, "")) != SHARD_VALUE:
        problems.append(
            f"{PROXY_MCP_JOB} has {SHARD_VAR}={env.get(SHARD_VAR)!r}, not {SHARD_VALUE}"
        )
    if strategy.get("fail-fast", True) is not False:
        problems.append(f"a failing {PROXY_MCP_JOB} shard cancels the others")
    if str(env.get("PYTHONUNBUFFERED", "")) != "1":
        problems.append(
            f"{PROXY_MCP_JOB} buffers its output, so a log shows no timings"
        )
    if not any(
        s.get("run", "").strip() == "pixi run test-proxy-mcp"
        for s in job.get("steps", [])
    ):
        problems.append(f"{PROXY_MCP_JOB} does not run test-proxy-mcp")
    return problems


BROWSER_PREFIX = "browser-"
CHROMIUM_INSTALL = "playwright install --with-deps chromium"
NOT_CANCELED = "!cancelled()"  # spelling-ok: GitHub Actions spells its function so
SUITE = re.compile(r"pixi run (test-[\w-]+)")


def browser_job_problems(workflow: dict) -> list[str]:
    """The Chromium suites are dealt into browser-* jobs. Each job installs Chromium
    before its first suite; each suite after the first runs even when one before it
    failed (one failure must not hide the rest); and no suite runs in two of them."""
    browser = {n: j for n, j in jobs(workflow).items() if n.startswith(BROWSER_PREFIX)}
    if not browser:
        return [f"there is no {BROWSER_PREFIX}* job, so no suite runs in Chromium"]
    problems = []
    seen: dict[str, str] = {}
    for name, job in browser.items():
        steps = job.get("steps", [])
        installed = next(
            (i for i, s in enumerate(steps) if CHROMIUM_INSTALL in s.get("run", "")),
            None,
        )
        suites = [(i, s) for i, s in enumerate(steps) if SUITE.search(s.get("run", ""))]
        if not suites:
            problems.append(f"{name} runs no suite")
            continue
        if installed is None or installed > suites[0][0]:
            problems.append(f"{name} runs a suite before it installs Chromium")
        for _, step in suites[1:]:
            if NOT_CANCELED not in str(step.get("if", "")):
                problems.append(
                    f"in {name}, {step['run']!r} does not run after an earlier failure"
                )
        for _, step in suites:
            suite = SUITE.search(step["run"])[1]
            if suite in seen:
                problems.append(f"{suite} runs in both {seen[suite]} and {name}")
            seen[suite] = name
    return problems


def every_rule(
    workflow: dict, tasks: dict, files: list[str], compose: dict
) -> list[str]:
    return [
        *untested_tasks(workflow, tasks),
        *orphan_tests(tasks, files),
        *no_server_pytest(workflow),
        *no_mcp_pytest(workflow),
        *server_matrix_problems(workflow),
        *proxy_mcp_shard_problems(workflow),
        *browser_job_problems(workflow),
        *stack_suite_order(workflow),
        *skips_allowed(workflow),
        *swallowed_failures(workflow),
        *missing_timeouts(workflow),
        *postgres_drift(workflow, compose),
        *aggregate_problems(workflow),
        *engine_problems(workflow),
        *trigger_problems(workflow),
        *permission_problems(workflow),
        *actionlint_missing(workflow),
    ]


# --- tests ------------------------------------------------------------------


def main() -> int:
    workflow = load(TEST_WORKFLOW)
    tasks = pixi_tasks()
    files = test_files()
    compose = load(ROOT / "compose.yaml")

    print("The real configuration")
    problems = every_rule(workflow, tasks, files, compose)
    check(
        "every rule passes on .github/workflows/test.yml",
        not problems,
        "; ".join(problems),
    )
    check(
        "there are pixi test tasks to cover",
        sum(t.startswith(TEST_TASK_PREFIX) for t in tasks) >= 10,
    )
    check("there are test files to cover", len(files) >= 10)

    every = {path.name: load(path) for path in sorted(WORKFLOWS.glob("*.yml"))}
    check(
        "every workflow running the prek hooks sets REQUIRE_TESTS",
        not hooks_may_skip(every),
        "; ".join(hooks_may_skip(every)),
    )
    check(
        "lint.yml runs the prek hooks (so the rule above covers it)",
        any("prek run" in cmd for cmd in run_commands(load(LINT_WORKFLOW))),
    )

    print("Every workflow file")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        wf = load(path)
        check(f"{path.name}: parses and has jobs", bool(jobs(wf)))
        check(
            f"{path.name}: has a permissions block", wf.get("permissions") is not None
        )
        check(
            f"{path.name}: does not use pull_request_target",
            "pull_request_target" not in triggers(wf),
        )

    print("Mutation tests: each rule must notice when it is broken")

    broken = copy.deepcopy(workflow)
    for job in jobs(broken).values():
        job["steps"] = [s for s in job["steps"] if "test-pdf" not in s.get("run", "")]
    check(
        "a suite dropped from CI is noticed",
        any("test-pdf" in p for p in untested_tasks(broken, tasks)),
    )

    check(
        "a new pixi test task nobody wired into CI is noticed",
        any(
            "test-brand-new" in p
            for p in untested_tasks(
                workflow, {**tasks, "test-brand-new": "python x.py"}
            )
        ),
    )
    check(
        "a test file no task runs is noticed",
        any(
            "test_orphan.py" in p
            for p in orphan_tests(tasks, [*files, "test_orphan.py"])
        ),
    )

    broken = copy.deepcopy(workflow)
    del broken["env"][REQUIRE_VAR]
    check("REQUIRE_TESTS removed is noticed", bool(skips_allowed(broken)))
    broken["env"][REQUIRE_VAR] = "0"
    check("REQUIRE_TESTS set to 0 is noticed", bool(skips_allowed(broken)))

    broken = copy.deepcopy(every)
    del broken[LINT_WORKFLOW.name]["env"][REQUIRE_VAR]
    check(
        "REQUIRE_TESTS removed from lint.yml, which runs prek, is noticed",
        any(LINT_WORKFLOW.name in p for p in hooks_may_skip(broken)),
    )

    broken = copy.deepcopy(workflow)
    jobs(broken)["browser-3"]["steps"][-1]["continue-on-error"] = True
    check("continue-on-error on a step is noticed", bool(swallowed_failures(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)["stack"]["continue-on-error"] = True
    check("continue-on-error on a job is noticed", bool(swallowed_failures(broken)))

    broken = copy.deepcopy(workflow)
    del jobs(broken)["server"]["timeout-minutes"]
    check("a job with no timeout is noticed", bool(missing_timeouts(broken)))

    broken = copy.deepcopy(workflow)
    jobs(broken)[SERVER_JOB]["services"][POSTGRES_SERVICE]["image"] = "postgres:16"
    check(
        "Postgres drifting from compose.yaml is noticed",
        bool(postgres_drift(broken, compose)),
    )

    broken = copy.deepcopy(workflow)
    for step in jobs(broken)[SERVER_JOB]["steps"]:
        step.pop("working-directory", None)
    check("pytest not run from server/ is noticed", bool(no_server_pytest(broken)))

    broken = copy.deepcopy(workflow)
    for step in jobs(broken)[SERVER_JOB]["steps"]:
        if step.get("working-directory") == "mcp":
            step.pop("working-directory")
    check("pytest not run from mcp/ is noticed", bool(no_mcp_pytest(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)[SERVER_JOB]["steps"] = [
        s
        for s in jobs(broken)[SERVER_JOB]["steps"]
        if "mcp[dev]" not in s.get("run", "")
    ]
    check("the MCP package not installed is noticed", bool(no_mcp_pytest(broken)))

    broken = copy.deepcopy(workflow)
    steps = jobs(broken)["stack"]["steps"]
    mcp_at = next(
        i for i, x in enumerate(steps) if x.get("run") == "pixi run test-stack-mcp"
    )
    steps.append(steps.pop(mcp_at))
    check(
        "the MCP stack suite moved after the end-to-end one is noticed",
        bool(stack_suite_order(broken)),
    )

    broken = copy.deepcopy(workflow)
    jobs(broken)[AGGREGATE_JOB]["needs"].remove("stack")
    check(
        "an aggregate that forgets a job is noticed", bool(aggregate_problems(broken))
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[AGGREGATE_JOB]["if"] = "${{ success() }}"
    check(
        "an aggregate that is skipped, not failed, is noticed",
        bool(aggregate_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[ENGINES_JOB]
    check("no engines job is noticed", bool(engine_problems(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)[ENGINES_JOB]["strategy"]["matrix"]["engine"] = ["firefox"]
    check("a missing WebKit is noticed", bool(engine_problems(broken)))
    broken = copy.deepcopy(workflow)
    del jobs(broken)[ENGINES_JOB]["env"]["TEST_BROWSER"]
    check(
        "an engine never passed to the tests is noticed", bool(engine_problems(broken))
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[ENGINES_JOB]["steps"][-1]
    check("a dropped suite is noticed", bool(engine_problems(broken)))
    broken = copy.deepcopy(workflow)
    del jobs(broken)[AGGREGATE_JOB]
    check("no aggregate job is noticed", bool(aggregate_problems(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)["brand_new"] = {
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 5,
        "steps": [],
    }
    check(
        "a new job the aggregate ignores is noticed", bool(aggregate_problems(broken))
    )

    print("Mutation tests: the split jobs (D-97)")

    def server_steps(wf: dict) -> list[dict]:
        return jobs(wf)[SERVER_JOB]["steps"]

    def leg_step(wf: dict, leg: str) -> dict:
        return next(
            s
            for s in server_steps(wf)
            if "pytest" in s.get("run", "") and f"'{leg}'" in str(s.get("if", ""))
        )

    broken = copy.deepcopy(workflow)
    jobs(broken)[SERVER_JOB]["strategy"]["matrix"]["suite"].remove("mcp")
    check(
        "a leg dropped from the server matrix is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    leg_step(broken, "app-role")["if"] = "${{ matrix.suite == 'app_role' }}"
    check(
        "a server step tied to a leg that does not exist (so runs in none) is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del leg_step(broken, "owner")["if"]
    check(
        "a server pytest step run in every leg is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del leg_step(broken, "app-role")["env"]
    check(
        "the restricted-role leg not connecting as the restricted role is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    leg_step(broken, "owner")["env"] = {APP_ROLE_VAR: "1"}
    check(
        "the owner leg connecting as the restricted role is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[SERVER_JOB]["env"][APP_ROLE_VAR] = "1"
    check(
        "TEST_APP_ROLE set for the whole server job is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    leg_step(broken, "mcp")["working-directory"] = "server"
    check(
        "the mcp leg running pytest from server/ is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[SERVER_JOB]["strategy"]["fail-fast"]
    check(
        "a server matrix that cancels its other legs is noticed",
        bool(server_matrix_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[SERVER_JOB]["services"][POSTGRES_SERVICE]["image"] = "postgres:17"
    check(
        "every server leg's Postgres drifting from compose.yaml is noticed",
        bool(postgres_drift(broken, compose)),
    )

    broken = copy.deepcopy(workflow)
    jobs(broken)[PROXY_MCP_JOB]["strategy"]["matrix"]["shard"].remove(3)
    check(
        "a proxy-mcp shard missing from the matrix is noticed",
        bool(proxy_mcp_shard_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[PROXY_MCP_JOB]["strategy"]["matrix"]["shard"] = [0, 1, 2, 3, 4]
    check(
        "proxy-mcp shards numbered from 0 are noticed",
        bool(proxy_mcp_shard_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[PROXY_MCP_JOB]["env"][SHARD_VAR] = "${{ matrix.shard }}/4"
    check(
        "a shard count written by hand, not taken from the matrix, is noticed",
        bool(proxy_mcp_shard_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[PROXY_MCP_JOB]["env"][SHARD_VAR]
    check(
        "proxy-mcp shards never told which they are is noticed",
        bool(proxy_mcp_shard_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[PROXY_MCP_JOB]["env"]["PYTHONUNBUFFERED"]
    check(
        "proxy-mcp buffering its output is noticed",
        bool(proxy_mcp_shard_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[PROXY_MCP_JOB]["strategy"]["fail-fast"] = True
    check(
        "a proxy-mcp shard canceling the others is noticed",
        bool(proxy_mcp_shard_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[PROXY_MCP_JOB]
    check("no proxy-mcp job is noticed", bool(proxy_mcp_shard_problems(broken)))

    broken = copy.deepcopy(workflow)
    del jobs(broken)["browser-2"]["steps"][-1]["if"]
    check(
        "a Chromium suite that does not run after an earlier failure is noticed",
        bool(browser_job_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    steps = jobs(broken)["browser-1"]["steps"]
    at = next(i for i, s in enumerate(steps) if CHROMIUM_INSTALL in s.get("run", ""))
    steps.append(steps.pop(at))
    check(
        "a browser job running suites before installing Chromium is noticed",
        bool(browser_job_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)["browser-3"]["steps"].append(
        {"if": f"${{{{ {NOT_CANCELED} }}}}", "run": "pixi run test-rules-banner"}
    )
    check(
        "a Chromium suite run in two browser jobs is noticed",
        bool(browser_job_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    for name in [n for n in jobs(broken) if n.startswith(BROWSER_PREFIX)]:
        del jobs(broken)[name]
    check("no browser job is noticed", bool(browser_job_problems(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)[AGGREGATE_JOB]["needs"].remove("browser-2")
    check(
        "an aggregate that forgets one browser job is noticed",
        bool(aggregate_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)["browser-2"]["timeout-minutes"]
    check("a browser job with no timeout is noticed", bool(missing_timeouts(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)["browser-1"]["steps"] = [
        s
        for s in jobs(broken)["browser-1"]["steps"]
        if "test-rules-banner" not in s.get("run", "")
    ]
    check(
        "a suite dropped while dealing them into browser jobs is noticed",
        any("test-rules-banner" in p for p in untested_tasks(broken, tasks)),
    )

    broken = copy.deepcopy(workflow)
    del broken[True]["pull_request"]
    check(
        "tests not running on pull_request is noticed", bool(trigger_problems(broken))
    )

    broken = copy.deepcopy(workflow)
    broken["permissions"] = {"contents": "write"}
    check(
        "write permissions on the test workflow are noticed",
        bool(permission_problems(broken)),
    )
    del broken["permissions"]
    check("a missing permissions block is noticed", bool(permission_problems(broken)))

    broken = copy.deepcopy(workflow)
    for job in jobs(broken).values():
        job["steps"] = [s for s in job["steps"] if "actionlint" not in s.get("run", "")]
    check("dropping actionlint is noticed", bool(actionlint_missing(broken)))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("workflow checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
