"""The architecture document build command: one entry point for keeping `docs/architecture/` true to the code.

    uv run python -m scripts.architecture_doc check        # CI: fail on any problem, one line per problem
    uv run python -m scripts.architecture_doc regenerate   # rewrite the code-derived regions in place

`check` fails on a missing section file or required heading, an index that does not link every section in order, a
broken relative link or anchor, a Mermaid block that does not render (mermaid-cli via `npx`), and a code-derived
region whose content differs from what its generator renders now. `--no-mermaid` skips rendering where Node is absent.

A code-derived region is delimited by `<!-- BEGIN GENERATED: <name> -->` and `<!-- END GENERATED: <name> -->`.
Generators import the live application modules; they never parse source text. Content outside markers is never
touched by `regenerate`. Spec: `.scratch/architecture-document/spec.md` (no ADR governs the document tooling).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from app import rbac

DOC_DIR = Path(__file__).resolve().parents[1] / "docs" / "architecture"
MERMAID_CLI = "@mermaid-js/mermaid-cli@12.2.0"
MERMAID_TIMEOUT_SECONDS = 300  # the first run downloads mermaid-cli and its headless Chromium


@dataclass(frozen=True)
class Section:
    file: str
    title: str
    headings: tuple[str, ...] = ()


# The document, in reading order. `index.md` holds the document-control block and links every other file in this order.
SECTIONS: tuple[Section, ...] = (
    Section(
        "index.md",
        "Portfolio Rebalancing: Architecture Document",
        ("Document control", "Reviewers", "Version history", "Contents"),
    ),
    Section(
        "00-executive-summary.md",
        "Executive Summary",
        ("Business problem", "Value", "How it works", "Roadmap headline"),
    ),
    Section(
        "01-introduction-and-goals.md",
        "1. Introduction and Goals",
        ("1.1 Requirements overview", "1.2 Quality goals", "1.3 Stakeholders"),
    ),
    Section(
        "02-architecture-constraints.md",
        "2. Architecture Constraints",
        ("2.1 Technical constraints", "2.2 Organisational constraints", "2.3 Conventions"),
    ),
    Section(
        "03-context-and-scope.md",
        "3. Context and Scope",
        ("3.1 Business context", "3.2 Technical context"),
    ),
    Section("04-solution-strategy.md", "4. Solution Strategy"),
    Section(
        "05-building-block-view.md",
        "5. Building Block View",
        ("5.1 Level 1: Containers", "5.2 Level 2: API process components"),
    ),
    Section(
        "06-runtime-view.md",
        "6. Runtime View",
        (
            "6.1 Analysis Run",
            "6.2 Tiered Decisions",
            "6.3 Report ingestion to Insight Review",
            "6.4 Assistant Question",
        ),
    ),
    Section(
        "07-deployment-view.md",
        "7. Deployment View",
        ("7.1 Logical deployment", "7.2 Reference deployment on Azure"),
    ),
    Section(
        "08-crosscutting-concepts.md",
        "8. Crosscutting Concepts",
        (
            "8.1 Deterministic engine ownership",
            "8.2 Audit recording",
            "8.3 LLM call shape and prompt versioning",
            "8.4 Recorded and live LLM modes",
            "8.5 SSE streaming",
            "8.6 Configuration service",
            "8.7 Idempotent migrations",
            "8.8 Authentication and authorization",
            "8.9 PII stance",
        ),
    ),
    Section("09-architecture-decisions.md", "9. Architecture Decisions"),
    Section(
        "10-quality-requirements.md",
        "10. Quality Requirements",
        ("10.1 Quality tree", "10.2 Quality scenarios", "10.3 Non-goals"),
    ),
    Section(
        "11-risks-and-technical-debt.md",
        "11. Risks and Technical Debt",
        ("11.1 Risks", "11.2 Technical debt"),
    ),
    Section("12-glossary.md", "12. Glossary"),
    Section(
        "13-roadmap.md",
        "Target / Production Roadmap",
        ("Roadmap items",),
    ),
    Section(
        "appendices.md",
        "Appendices",
        (
            "Appendix A: AI Governance",
            "Appendix B: Model inventory and evaluation",
            "Appendix C: Framework mapping",
            "Appendix D: Security and threat summary",
        ),
    ),
)


# ---- generators: each renders one Markdown table from a live application module ----


def rbac_matrix() -> str:
    """The role × permission matrix exactly as `app.rbac.PERMISSIONS` grants it, one row per permission."""
    roles = list(rbac.ROLES)
    permissions = sorted(set().union(*rbac.PERMISSIONS.values()))
    lines = [
        "| Permission | " + " | ".join(f"`{role}`" for role in roles) + " |",
        "| --- |" + " :---: |" * len(roles),
    ]
    for permission in permissions:
        cells = ["✓" if permission in rbac.PERMISSIONS[role] else "" for role in roles]
        lines.append(f"| `{permission}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


GENERATORS: dict[str, Callable[[], str]] = {
    "rbac-matrix": rbac_matrix,
}

REGION = re.compile(
    r"^<!-- BEGIN GENERATED: (?P<name>[\w-]+) -->\r?\n(?P<body>.*?)^<!-- END GENERATED: (?P=name) -->\r?$",
    re.MULTILINE | re.DOTALL,
)
MARKER = re.compile(r"^<!-- (?P<kind>BEGIN|END) GENERATED: (?P<name>[\w-]+) -->\r?$", re.MULTILINE)
MARKER_LIKE = re.compile(r"^[ \t]*<!--.*\bGENERATED\b.*$", re.MULTILINE)  # what a mistyped marker looks like


def read_raw(path: Path) -> str:
    """The file's text with its line endings untouched, so `regenerate` can rewrite it byte for byte."""
    with path.open(newline="") as f:
        return f.read()


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def region_body(name: str) -> str:
    """The text that belongs between the markers of region `name`: a blank line, the table, a blank line."""
    return "\n" + GENERATORS[name]().rstrip("\n") + "\n\n"


def render_region(name: str) -> str:
    return f"<!-- BEGIN GENERATED: {name} -->\n{region_body(name)}<!-- END GENERATED: {name} -->"


# ---- Markdown reading ----

FENCE = re.compile(r"^(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
INLINE_LINK = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
HTML_ID = re.compile(r"""\b(?:id|name)=["']([^"']+)["']""")
INLINE_CODE = re.compile(r"`+[^`]*`+")


@dataclass(frozen=True)
class Mermaid:
    file: Path
    line: int
    source: str


class Heading(NamedTuple):
    line: int
    level: int
    text: str


class Link(NamedTuple):
    line: int
    target: str


@dataclass
class Markdown:
    headings: list[Heading]
    links: list[Link]
    mermaid: list[Mermaid]
    html_ids: set[str]


def read_markdown(path: Path) -> Markdown:
    """Headings, link targets and Mermaid blocks of `path`, ignoring anything inside code fences or inline code."""
    md = Markdown(headings=[], links=[], mermaid=[], html_ids=set())
    fence: str | None = None
    fence_lang = ""
    fence_start = 0
    fence_lines: list[str] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        opener = FENCE.match(line.lstrip())
        if fence is not None:
            if opener and line.lstrip().startswith(fence) and not line.strip()[len(fence) :].strip():
                if fence_lang == "mermaid":
                    md.mermaid.append(Mermaid(path, fence_start, "\n".join(fence_lines) + "\n"))
                fence = None
            else:
                fence_lines.append(line)
            continue
        if opener:
            fence = opener.group(1)
            fence_lang = line.strip()[len(fence) :].strip().split(" ")[0].lower()
            fence_start, fence_lines = number, []
            continue
        if heading := HEADING.match(line):
            md.headings.append(Heading(number, len(heading.group(1)), heading.group(2)))
        prose = INLINE_CODE.sub("", line)
        md.links += [Link(number, target) for target in INLINE_LINK.findall(prose)]
        if ref := REFERENCE_DEF.match(prose):
            md.links.append(Link(number, ref.group(1)))
        md.html_ids.update(HTML_ID.findall(prose))
    return md


def slugify(heading: str) -> str:
    """The anchor GitHub gives a heading: link text kept, markup and punctuation dropped, spaces to hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip().lower()
    kept = "".join(c for c in text if c in " -_" or unicodedata.category(c)[0] in "LNM")
    return kept.replace(" ", "-")


def anchors(md: Markdown) -> set[str]:
    seen: dict[str, int] = {}
    result = set(md.html_ids)
    for heading in md.headings:
        slug = slugify(heading.text)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug if count == 0 else f"{slug}-{count}")
    return result


# ---- checks ----


@dataclass(frozen=True)
class Problem:
    file: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{_relative_to_cwd(self.file)}:{self.line}: {self.message}"


def _relative_to_cwd(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def check_structure(doc_dir: Path, docs: dict[Path, Markdown]) -> list[Problem]:
    problems: list[Problem] = []
    for section in SECTIONS:
        path = doc_dir / section.file
        if path not in docs:
            problems.append(Problem(path, 0, f"missing section file (expected '{section.title}')"))
            continue
        present = {heading.text for heading in docs[path].headings}
        titles = [heading.text for heading in docs[path].headings if heading.level == 1]
        if section.title not in titles:
            problems.append(Problem(path, 1, f"missing title heading '# {section.title}'"))
        problems += [
            Problem(path, 0, f"missing required heading '{heading}'")
            for heading in section.headings
            if heading not in present
        ]
    index = doc_dir / SECTIONS[0].file
    if index in docs:
        problems += _index_order_problems(index, docs[index])
    return problems


def _index_order_problems(index: Path, md: Markdown) -> list[Problem]:
    """Problems with the Contents section of the index, which must link every other section in reading order."""
    start = next((h.line for h in md.headings if h.text == "Contents"), None)
    if start is None:
        return []  # reported as a missing required heading
    end = next((h.line for h in md.headings if h.line > start and h.level <= 2), None)
    linked = [
        Path(link.target.split("#")[0]).name
        for link in md.links
        if start < link.line and (end is None or link.line < end) and not _external(link.target)
    ]
    order = [s.file for s in SECTIONS[1:]]
    problems = [Problem(index, 0, f"index does not link section '{file}'") for file in order if file not in linked]
    listed = [file for file in dict.fromkeys(linked) if file in order]
    if listed != [file for file in order if file in listed]:
        problems.append(Problem(index, 0, f"index lists sections out of order (expected {', '.join(order)})"))
    return problems


def _external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


def check_links(docs: dict[Path, Markdown]) -> list[Problem]:
    problems: list[Problem] = []
    cache: dict[Path, set[str]] = {}
    for path, md in docs.items():
        for line, target in md.links:
            if _external(target):
                continue
            file_part, _, anchor = target.partition("#")
            resolved = (path.parent / file_part).resolve() if file_part else path.resolve()
            if not resolved.exists():
                problems.append(Problem(path, line, f"broken link '{target}': {file_part} does not exist"))
                continue
            if not anchor:
                continue
            if resolved.suffix != ".md":
                problems.append(Problem(path, line, f"broken link '{target}': anchors are only checked in Markdown"))
                continue
            if resolved not in cache:
                cache[resolved] = anchors(docs.get(resolved) or read_markdown(resolved))
            if anchor not in cache[resolved]:
                problems.append(Problem(path, line, f"broken anchor '{target}': no heading '#{anchor}' there"))
    return problems


def check_regions(docs: dict[Path, Markdown]) -> list[Problem]:
    problems: list[Problem] = []
    for path in docs:
        text = read_raw(path)
        problems += _marker_problems(path, text)
        for region in REGION.finditer(text):
            name = region.group("name")
            line = line_of(text, region.start())
            if name in GENERATORS and region.group("body") != region_body(name):
                problems.append(
                    Problem(
                        path,
                        line,
                        f"stale generated region '{name}' (run: uv run python -m scripts.architecture_doc regenerate)",
                    )
                )
    return problems


def _marker_problems(path: Path, text: str) -> list[Problem]:
    problems = [
        Problem(path, line_of(text, m.start()), f"malformed generated-region marker '{m.group(0).strip()}'")
        for m in MARKER_LIKE.finditer(text)
        if not MARKER.fullmatch(m.group(0))
    ]
    open_name: str | None = None
    open_line = 0
    for marker in MARKER.finditer(text):
        line = line_of(text, marker.start())
        kind, name = marker.group("kind"), marker.group("name")
        if kind == "BEGIN":
            if open_name is not None:
                problems.append(_unclosed(path, open_line, open_name))
            if name not in GENERATORS:
                problems.append(Problem(path, line, f"unknown generator '{name}' (known: {', '.join(GENERATORS)})"))
            open_name, open_line = name, line
        elif name != open_name:
            problems.append(Problem(path, line, f"END marker for '{name}' has no matching BEGIN"))
        else:
            open_name = None
    if open_name is not None:
        problems.append(_unclosed(path, open_line, open_name))
    return problems


def _unclosed(path: Path, line: int, name: str) -> Problem:
    return Problem(path, line, f"generated region '{name}' is not closed")


def check_mermaid(blocks: list[Mermaid]) -> list[Problem]:
    """One problem per Mermaid block that mermaid-cli cannot render; none when every block renders."""
    if not blocks:
        return []
    npx = shutil.which("npx")
    if npx is None:
        return [Problem(blocks[0].file, blocks[0].line, "npx not found: cannot render Mermaid (use --no-mermaid)")]
    with tempfile.TemporaryDirectory(prefix="architecture-doc-") as tmp:
        work = Path(tmp)
        config = work / "puppeteer.json"
        config.write_text(json.dumps({"args": ["--no-sandbox"]}))  # CI runners forbid Chromium's user-ns sandbox
        combined = work / "all.md"
        combined.write_text("".join(f"```mermaid\n{block.source}```\n\n" for block in blocks))
        batch_error = _render(npx, config, combined, work / "all-out.md")  # one Chromium start in the common case
        if batch_error is None:
            return []
        problems = []
        for number, block in enumerate(blocks):
            source = work / f"block-{number}.mmd"
            source.write_text(block.source)
            if (error := _render(npx, config, source, work / f"block-{number}.svg")) is not None:
                problems.append(Problem(block.file, block.line, f"Mermaid block does not render: {error}"))
        if not problems:  # the batch failed but every block renders alone: report the batch failure itself
            problems.append(Problem(blocks[0].file, blocks[0].line, f"Mermaid rendering failed: {batch_error}"))
        return problems


def _render(npx: str, config: Path, source: Path, output: Path) -> str | None:
    """None when mermaid-cli renders `source`; otherwise its first error line."""
    command = [npx, "--yes", MERMAID_CLI, "--quiet", "-p", str(config), "-i", str(source), "-o", str(output)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=MERMAID_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"mermaid-cli timed out after {MERMAID_TIMEOUT_SECONDS}s"
    if result.returncode == 0:
        return None
    lines = [line.strip() for line in (result.stderr + result.stdout).splitlines() if line.strip()]
    errors = [line for line in lines if "error" in line.lower()]
    return (errors or lines or [f"mermaid-cli exited {result.returncode}"])[0]


# ---- modes ----


def load(doc_dir: Path) -> dict[Path, Markdown]:
    return {path.resolve(): read_markdown(path) for path in sorted(doc_dir.glob("*.md"))}


def check(doc_dir: Path, mermaid: bool = True) -> list[Problem]:
    docs = load(doc_dir)
    problems = check_structure(doc_dir.resolve(), docs) + check_links(docs) + check_regions(docs)
    if mermaid:
        problems += check_mermaid([block for md in docs.values() for block in md.mermaid])
    return problems


def regenerate(doc_dir: Path) -> tuple[list[Path], list[Problem]]:
    """Every region in a file with well-formed markers holds its generator's current output; returns the files
    changed and the marker problems that left a file untouched."""
    changed: list[Path] = []
    problems: list[Problem] = []
    for path in sorted(doc_dir.resolve().glob("*.md")):
        text = read_raw(path)
        marker_problems = _marker_problems(path, text)
        if marker_problems:
            problems += marker_problems
            continue
        updated = REGION.sub(lambda m: render_region(m.group("name")), text)
        if updated != text:
            with path.open("w", newline="") as f:
                f.write(updated)
            changed.append(path)
    return changed, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="architecture_doc", description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=["check", "regenerate"])
    parser.add_argument("--doc-dir", type=Path, default=DOC_DIR, help="the architecture folder (default: %(default)s)")
    parser.add_argument("--no-mermaid", action="store_true", help="check: skip rendering Mermaid blocks")
    args = parser.parse_args(argv)
    if not args.doc_dir.is_dir():
        print(f"{args.doc_dir}: not a directory")
        return 2
    if args.mode == "check":
        problems = check(args.doc_dir, mermaid=not args.no_mermaid)
        for problem in problems:
            print(problem)
        print(f"architecture document: {len(problems)} problem(s)" if problems else "architecture document: OK")
        return 1 if problems else 0
    changed, problems = regenerate(args.doc_dir)
    for problem in problems:
        print(problem)
    for path in changed:
        print(f"regenerated {_relative_to_cwd(path)}")
    if not changed and not problems:
        print("architecture document: generated regions already current")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
