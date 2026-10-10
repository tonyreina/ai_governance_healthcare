#!/usr/bin/env python3
"""Generate docs/frameworks/<id>-checklist.md from each framework definition.

One generator for every framework (#168, D-75). It reads each
app/frameworks/<id>/framework.json, the definition the app is built from, and
writes the published checklist page for it, so the page cannot drift from the
definition. The page's own prose (its introduction and a few labels) sits beside
the definition in app/frameworks/<id>/docs.toml; a definition without one still
gets a page, written with neutral defaults.

What the definition decides about the page:

* `keys.section` and `keys.category` name the headings ("Stage 1", "Domain A").
* `categoriesOn: "sections"` groups the sections under their category, with a
  heading per category; otherwise each item carries its category in a column,
  and a table of the categories leads the page.
* `whos` adds a column saying who answers each item.
* `crossRefs` on an item add a column naming the other framework's criteria.
* `source` adds a "Source" section citing it.

Run via: pixi run gen-docs. `--out DIR` writes the pages somewhere else, which is
how tests/test_framework_docs.py compares a fresh run with the committed pages.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import tomllib
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORKS = ROOT / "app" / "frameworks"
OUT = ROOT / "docs" / "frameworks"
DEFINITION = "framework.json"
DOCS_CONFIG = "docs.toml"

# Prose stays within the repository's 80-column Markdown style, so a generated
# page passes the same rumdl check as a hand-written one.
WRAP = 78
DASH = "—"


class CategoriesOn(StrEnum):
    """Where a definition's categories attach: to each item, or to each section."""

    ITEMS = "items"
    SECTIONS = "sections"


@dataclass(frozen=True)
class PageText:
    """A page's own words. Every field is optional in docs.toml.

    `intro`, `footer` and `citation` are `string.Template`s: `$total` is the
    number of items, `$definition` the definition's path in the repository, and
    `$title`, `$journal`, `$year` and `$doi` (citation only) come from the
    definition's `source`.
    """

    title: str = ""
    intro: str = ""
    count_noun: str = "items"
    item_column: str = "Item"
    bold_numbers: bool = False
    italic_section_body: bool = False
    relation_labels: dict[str, str] = field(default_factory=dict)
    citation: str = "*$title.* $journal $year. [DOI: $doi](https://doi.org/$doi)"
    footer: str = ""


DEFAULT_INTRO = """\
The $total items of $name, in the order the dashboard presents them.

!!! info "Generated file"

    This page is generated from `$definition` by
    `scripts/gen_framework_docs.py` (`pixi run gen-docs`). Edit the
    definition, not this page."""


class DefinitionError(ValueError):
    """A definition or its docs.toml cannot be turned into a page."""


def load_page_text(path: Path) -> PageText:
    if not path.exists():
        return PageText()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(PageText)}
    unknown = sorted(set(raw) - known)
    if unknown:
        # A misspelled key would otherwise be ignored and the default used,
        # silently: name it instead.
        raise DefinitionError(f"{path}: unknown key(s) {', '.join(unknown)}")
    return PageText(**raw)


def heading_word(key: str) -> str:
    return key[:1].upper() + key[1:]


def cell(text: str) -> str:
    """Text for a table cell: a pipe would end the cell early."""
    return text.replace("|", "\\|")


def load_definitions(root: Path) -> dict[str, dict]:
    defs = {}
    for path in sorted(root.glob(f"*/{DEFINITION}")):
        defn = json.loads(path.read_text(encoding="utf-8"))
        if defn.get("id") != path.parent.name:
            raise DefinitionError(
                f"{path}: id {defn.get('id')!r} does not match its directory"
            )
        defs[defn["id"]] = defn
    return defs


def render(defn: dict, text: PageText, definitions: dict[str, dict], rel: str) -> str:
    """The page for one definition, as Markdown. `rel` is its repository path."""
    keys = defn.get("keys", {})
    section_word = heading_word(keys.get("section", "section"))
    category_word = heading_word(keys.get("category", "category"))
    categories = {c["id"]: c["name"] for c in defn.get("categories", [])}
    categories_on = CategoriesOn(defn.get("categoriesOn", CategoriesOn.ITEMS))
    body_key = keys.get("sectionBody", "")
    sections = defn["sections"]
    total = sum(len(s["items"]) for s in sections)
    show_category = bool(categories) and categories_on is CategoriesOn.ITEMS
    show_who = bool(defn.get("whos"))
    cross = next(
        (i["crossRefs"] for s in sections for i in s["items"] if i.get("crossRefs")),
        None,
    )
    cross_name = None
    if cross:
        target = definitions.get(cross["framework"], {})
        cross_name = target.get("name", cross["framework"].upper())

    subst = {"total": total, "name": defn["name"], "definition": rel}
    blocks: list[str] = [
        f"# {text.title or defn['name'] + ' checklist'}",
        Template(text.intro or DEFAULT_INTRO).substitute(subst).strip("\n"),
    ]

    if show_category:
        blocks.append(f"## {category_word}s")
        blocks.append(
            "\n".join(
                [f"| Tag | {category_word} |", "|---|---|"]
                + [f"| **{k}** | {cell(v)} |" for k, v in categories.items()]
            )
        )

    header = ["", text.item_column]
    if show_category:
        header.append(category_word)
    if show_who:
        header.append("Who answers")
    if cross_name:
        header.append(cross_name)
    # The number column has no heading, written "| |" as the pages always were.
    header_rows = [
        "| | " + " | ".join(header[1:]) + " |",
        "|" + "---|" * len(header),
    ]

    group = None
    level = "##"
    for section in sections:
        if categories_on is CategoriesOn.SECTIONS:
            level = "###"
            if section["category"] != group:
                group = section["category"]
                blocks.append(
                    f"## {category_word} {group}: {categories.get(group, group)}"
                )
        blocks.append(f"{level} {section_word} {section['n']}: {section['title']}")
        body = section.get(body_key, "") if body_key else ""
        if body:
            if text.italic_section_body:
                body = f"*{body}*"
            blocks.append(textwrap.fill(body, width=WRAP))
        items = section["items"]
        blocks.append(f"*{len(items)} {text.count_noun}.*")

        rows = list(header_rows)
        for pos, item in enumerate(items, 1):
            num = item.get("num") or f"{section['n']}.{pos}"
            row = [f"**{num}**" if text.bold_numbers else num, cell(item["text"])]
            if show_category:
                row.append(f"**{item['category']}**")
            if show_who:
                row.append(item.get("who") or DASH)
            if cross_name:
                refs = item.get("crossRefs") or {}
                relation = refs.get("relation") or ""
                label = text.relation_labels.get(relation, relation or DASH)
                if refs.get("ids"):
                    label += f" {DASH} " + ", ".join(f"`{i}`" for i in refs["ids"])
                row.append(label)
            rows.append("| " + " | ".join(row) + " |")
        blocks.append("\n".join(rows))

    source = defn.get("source")
    if source:
        blocks.append("## Source")
        citation = Template(text.citation).substitute({**subst, **source})
        blocks.append(textwrap.fill(citation, width=WRAP))

    if text.footer:
        blocks.append(Template(text.footer).substitute(subst).strip("\n"))

    return "\n\n".join(blocks) + "\n"


def generate(frameworks: Path, out: Path) -> list[Path]:
    """Write a page for every definition under `frameworks` into `out`."""
    definitions = load_definitions(frameworks)
    if not definitions:
        raise DefinitionError(f"no {DEFINITION} under {frameworks}")
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fid, defn in definitions.items():
        directory = frameworks / fid
        # Where the definition lives in the repository, whatever directory this
        # run read it from, so a run over a copy writes the same page.
        rel = f"app/frameworks/{fid}/{DEFINITION}"
        page = render(defn, load_page_text(directory / DOCS_CONFIG), definitions, rel)
        target = out / f"{fid}-checklist.md"
        target.write_text(page, encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frameworks", type=Path, default=FRAMEWORKS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    try:
        written = generate(args.frameworks, args.out)
    except (DefinitionError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in written:
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
