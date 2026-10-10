# Example checklist

The 8 checks of the example framework, which shows how to
[bring your own](custom.md).

!!! warning "A made-up framework"

    This is not a standard and is not guidance. It exists to be copied.

!!! info "Generated file"

    This page is generated from `app/frameworks/example/framework.json` by
    `scripts/gen_framework_docs.py` (`pixi run gen-docs`). Edit the
    definition, not this page.

## Themes

| Tag | Theme |
|---|---|
| **benefit** | Benefit |
| **risk** | Risk |
| **oversight** | Oversight |

## Step 1: Plan

Say what the tool is for and who answers for it.

*3 checks.*

| | Check | Theme |
|---|---|---|
| 1.1 | The intended use is written down and agreed | **benefit** |
| 1.2 | A named person is accountable for the tool | **oversight** |
| 1.3 | Foreseeable harms are listed with a mitigation for each | **risk** |

## Step 2: Test

Check the tool works here, for the people it will serve.

*3 checks.*

| | Check | Theme |
|---|---|---|
| 2.1 | Performance is measured on local data | **benefit** |
| 2.2 | Results are compared across patient groups | **risk** |
| 2.3 | Staff know what to do when the tool is wrong or down | **oversight** |

## Step 3: Run

Watch the tool in use and decide, on a schedule, whether to keep it.

*2 checks.*

| | Check | Theme |
|---|---|---|
| 3.1 | Drift and errors are monitored, with a named reviewer | **risk** |
| 3.2 | Users can report a problem and get an answer | **oversight** |
