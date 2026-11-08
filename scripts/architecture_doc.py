"""The architecture document build command: one entry point for keeping `docs/architecture/` true to the code.

    uv run python -m scripts.architecture_doc check        # CI: fail on any problem, one line per problem
    uv run python -m scripts.architecture_doc regenerate   # rewrite the code-derived regions in place
    uv run python -m scripts.architecture_doc build        # per release: the stamped PDF in build/architecture/

`check` fails on a missing section file or required heading, an index that does not link every section in order, a
broken relative link or anchor, a Mermaid block that does not render (mermaid-cli via `npx`), and a code-derived
region whose content differs from what its generator renders now. `--no-mermaid` skips rendering where Node is absent.

A code-derived region is delimited by `<!-- BEGIN GENERATED: <name> -->` and `<!-- END GENERATED: <name> -->`.
Generators import the live application modules; they never parse source text. Content outside markers is never
touched by `regenerate`.

`build` refuses a dirty working tree (so the stamped commit SHA is the content) and a document that fails `check`. It
prints a PDF whose cover is stamped with the version (last Version history row of the index), status, commit SHA and
commit date, followed by the document-control block and every section in index order. Mermaid is pre-rendered to SVG
and the page is printed by the headless Chromium bundled with mermaid-cli; no pandoc or WeasyPrint. Not run in CI.

Spec: `.scratch/architecture-document/spec.md` (no ADR governs the document tooling).
"""

import argparse
import base64
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app import audit, config_service, prompts, rbac, settings

DOC_DIR = Path(__file__).resolve().parents[1] / "docs" / "architecture"
MERMAID_CLI = "@mermaid-js/mermaid-cli@12.2.0"
MERMAID_TIMEOUT_SECONDS = 300  # the first run downloads mermaid-cli and its headless Chromium
PUPPETEER_ARGS = ["--no-sandbox"]  # CI runners forbid Chromium's user-namespace sandbox; we only load our own HTML
PRINT_SCRIPT = Path(__file__).resolve().with_name("architecture_doc_print.mjs")


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


def prompt_versions() -> str:
    """Every registered prompt (`app.prompts.ALL`) with the version logged on its LLM Exchanges and recording keys."""
    lines = ["| Prompt | Version | Logged as |", "| --- | --- | --- |"]
    lines += [f"| `{prompt.name}` | `{prompt.version}` | `{prompt.label}` |" for prompt in prompts.ALL]
    return "\n".join(lines)


def audit_event_types() -> str:
    """Every Audit Event type `app.audit.record` accepts (`app.audit.EVENT_TYPES`), in declaration order."""
    lines = ["| Audit Event type |", "| --- |"]
    lines += [f"| `{event_type}` |" for event_type in audit.EVENT_TYPES]
    return "\n".join(lines)


def _cell(value: object) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _setting_rows(path: str, value: object) -> list[str]:
    """One row per setting; a group whose members are all plain values (a band, a per-profile map) stays on one row."""
    if not isinstance(value, dict):
        return [f"| `{path}` | {_cell(value)} |"]
    if not any(isinstance(setting, dict) for setting in value.values()):
        return [f"| `{path}` | " + ", ".join(f"{key} {_cell(setting)}" for key, setting in value.items()) + " |"]
    return [row for key, setting in value.items() for row in _setting_rows(f"{path}.{key}", setting)]


def config_defaults() -> str:
    """The business config a fresh database starts with: the defaults of `app.config_service.Config`."""
    lines = ["| Setting | Default |", "| --- | --- |"]
    for key, value in config_service.Config().model_dump().items():
        lines += _setting_rows(key, value)
    return "\n".join(lines)


def assistant_limits() -> str:
    """One row per Assistant limit, as shipped: every numeric `assistant_*` field of `app.settings.Settings` (so the
    eval-file path is not one), with its default value and its description. The values are the code's defaults, never
    this machine's environment. Raises ValueError for a limit with no description."""
    lines = ["| Setting | Default | Effect |", "| --- | --- | --- |"]
    for name, field in settings.Settings.model_fields.items():
        if name.startswith("assistant_") and field.annotation in (int, float):
            if not field.description:
                raise ValueError(f"Settings.{name} needs a description: it is the Effect column of 'assistant-limits'")
            lines.append(f"| `APP_{name.upper()}` | {field.default} | {field.description} |")
    return "\n".join(lines)


GENERATORS: dict[str, Callable[[], str]] = {
    "rbac-matrix": rbac_matrix,
    "prompt-versions": prompt_versions,
    "audit-event-types": audit_event_types,
    "config-defaults": config_defaults,
    "assistant-limits": assistant_limits,
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
HTML_ANCHOR = re.compile(r"""\b(id|name)=["']([^"']+)["']""")
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


def heading_anchor(heading: str, seen: dict[str, int]) -> str:
    """The anchor of `heading`, counting it in `seen`: GitHub suffixes a repeated slug with -1, -2, ..."""
    slug = slugify(heading)
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def anchors(md: Markdown) -> set[str]:
    seen: dict[str, int] = {}
    return set(md.html_ids) | {heading_anchor(heading.text, seen) for heading in md.headings}


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
    with tempfile.TemporaryDirectory(prefix="architecture-doc-") as tmp:
        return render_mermaid(blocks, Path(tmp))[1]


def render_mermaid(blocks: list[Mermaid], work: Path) -> tuple[list[str], list[Problem]]:
    """The SVG of every block, in order, and no problems; or no SVGs and one problem per block that does not render.
    `work` is a scratch folder."""
    if not blocks:
        return [], []
    npx = shutil.which("npx")
    if npx is None:
        return [], [
            Problem(blocks[0].file, blocks[0].line, "npx not found: cannot render Mermaid (check: --no-mermaid)")
        ]
    config = work / "puppeteer.json"
    config.write_text(json.dumps({"args": PUPPETEER_ARGS}))
    combined = work / "all.md"
    combined.write_text("".join(f"```mermaid\n{block.source}```\n\n" for block in blocks))
    batch_error = _render(npx, config, combined, work / "all-out.md")  # one Chromium start in the common case
    if batch_error is None:  # mermaid-cli numbers the diagrams of `all-out.md` as all-out-1.svg, all-out-2.svg, ...
        return [(work / f"all-out-{number}.svg").read_text() for number in range(1, len(blocks) + 1)], []
    problems = []
    for number, block in enumerate(blocks):
        source = work / f"block-{number}.mmd"
        source.write_text(block.source)
        if (error := _render(npx, config, source, work / f"block-{number}.svg")) is not None:
            problems.append(Problem(block.file, block.line, f"Mermaid block does not render: {error}"))
    if not problems:  # the batch failed but every block renders alone: report the batch failure itself
        problems.append(Problem(blocks[0].file, blocks[0].line, f"Mermaid rendering failed: {batch_error}"))
    return [], problems


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
    first = next((n for n, line in enumerate(lines) if "error" in line.lower()), None)
    if first is None:
        return lines[0] if lines else f"mermaid-cli exited {result.returncode}"
    error = lines[first].replace(" on line ", " on diagram line ")
    context = lines[first + 1] if first + 1 < len(lines) else ""
    return f"{error} {context}" if context.startswith("...") else error  # mermaid quotes the offending source


# ---- build: the frozen, stamped PDF ----
#
# Mermaid is pre-rendered to SVG with mermaid-cli, the sections are assembled into one HTML file in reading order with
# an embedded stylesheet behind a stamped cover, and the HTML is printed to PDF by the headless Chromium that
# mermaid-cli's Puppeteer already downloads (`architecture_doc_print.mjs`). No pandoc, no WeasyPrint.

PRINT_TIMEOUT_SECONDS = 300


class BuildError(Exception):
    """The build cannot produce a truthful PDF. The message says why; `problems` lists the document problems found."""

    def __init__(self, message: str, problems: list[Problem] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


@dataclass(frozen=True)
class Stamp:
    """What the cover certifies: which version of the document, at which commit, in which status."""

    title: str
    version: str
    status: str
    owner: str
    sha: str
    date: str  # the commit date, so rebuilding the same commit stamps the same date


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise BuildError("git not found: build stamps the commit SHA and needs git") from None
    except subprocess.CalledProcessError as e:
        raise BuildError(f"git {args[0]} failed: {e.stderr.strip()}") from None
    return result.stdout.rstrip()  # keep leading spaces: `status --porcelain` starts lines with them


def _clean_repository(doc_dir: Path) -> Path:
    """The top level of the repository holding `doc_dir`, whose working tree has no change against HEAD."""
    top = Path(_git(doc_dir, "rev-parse", "--show-toplevel")).resolve()
    changes = _git(top, "status", "--porcelain", "--untracked-files=all").splitlines()
    if changes:
        listed = "\n".join(f"  {change}" for change in changes[:20])
        more = f"\n  ... and {len(changes) - 20} more" if len(changes) > 20 else ""
        raise BuildError(
            f"working tree is dirty ({len(changes)} change(s)): commit or stash them first, so the commit SHA stamped "
            f"on the cover is the content of the PDF\n{listed}{more}"
        )
    return top


def _table_under(text: str, heading: str) -> list[list[str]]:
    """The body rows of the first table after heading `heading`, each a list of stripped cells."""
    lines = text.splitlines()
    start = next((n for n, line in enumerate(lines) if (m := HEADING.match(line)) and m.group(2) == heading), None)
    if start is None:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        if HEADING.match(line) or (rows and not line.startswith("|")):
            break
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return [row for row in rows[1:] if not all(re.fullmatch(r":?-+:?", cell) for cell in row)]


def _stamp(doc_dir: Path, top: Path) -> Stamp:
    """The stamp for HEAD: version from the last Version history row, status and owner from Document control."""
    index = doc_dir / SECTIONS[0].file
    text = index.read_text()
    control = {row[0]: row[1] for row in _table_under(text, "Document control") if len(row) >= 2}
    history = _table_under(text, "Version history")
    missing = [field for field in ("Status", "Owner") if not control.get(field)]
    if missing or not history or not history[-1][0]:
        what = [f"no '{field}' row in the Document control table" for field in missing]
        what += [] if history and history[-1][0] else ["no version in the last row of the Version history table"]
        raise BuildError(f"{_relative_to_cwd(index)}: cannot stamp the cover: {'; '.join(what)}")
    exported = history[-1][3] if len(history[-1]) > 3 else ""
    if exported != control["Status"]:
        raise BuildError(
            f"{_relative_to_cwd(index)}: cannot stamp the cover: Document control says Status '{control['Status']}' "
            f"but the Version history row for {history[-1][0]} says '{exported}'"
        )
    return Stamp(
        title=SECTIONS[0].title,
        version=history[-1][0],
        status=control["Status"],
        owner=control["Owner"],
        sha=_git(top, "rev-parse", "HEAD"),
        date=_git(top, "show", "--no-patch", "--format=%cs", "HEAD"),
    )


def _github_url(top: Path) -> str | None:
    """`https://github.com/<owner>/<repo>` when `origin` is on GitHub, so links out of the document can be pinned."""
    try:
        origin = _git(top, "remote", "get-url", "origin")
    except BuildError:
        return None
    match = re.match(
        r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$", origin
    )
    return f"https://github.com/{match.group(1)}" if match else None


@dataclass
class _Assembly:
    """Where every link of the assembled document points: in-document anchors, or GitHub at the stamped commit."""

    top: Path
    sha: str
    github: str | None
    anchors: dict[Path, str]  # section file -> its anchor prefix in the assembled HTML

    def href(self, target: str, source: Path) -> str | None:
        """The href `target` (written in `source`) gets in the PDF; None when it can point nowhere outside the repo."""
        if _external(target):
            return target
        file_part, _, anchor = urllib.parse.unquote(target).partition("#")
        resolved = (source.parent / file_part).resolve() if file_part else source
        if resolved in self.anchors:
            return f"#{self.anchors[resolved]}--{anchor}" if anchor else f"#{self.anchors[resolved]}"
        if self.github is None or not resolved.is_relative_to(self.top):
            return None
        kind = "tree" if resolved.is_dir() else "blob"
        path = urllib.parse.quote(resolved.relative_to(self.top).as_posix())
        return f"{self.github}/{kind}/{self.sha}/{path}" + (f"#{anchor}" if anchor else "")


def _markdown() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])


def _diagram(svg: str, number: int) -> str:
    """An inline SVG figure. mermaid-cli names every SVG `my-svg` and scopes its styles to that id, so each is renamed."""
    svg = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", svg).replace("my-svg", f"mermaid-{number}")
    return f'<figure class="diagram">{svg}</figure>\n'


IMAGE_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _is_mermaid(token: Token) -> bool:
    return token.type == "fence" and token.info.strip().split(" ")[0].lower() == "mermaid"


def _rewrite(tokens: list[Token], source: Path, prefix: str, assembly: _Assembly) -> None:
    """Headings and HTML anchors get ids prefixed with the section's, so they are unique in the assembled document;
    links point inside the PDF or at GitHub; local images are embedded. Raises BuildError for an image the PDF
    cannot embed."""
    seen: dict[str, int] = {}
    prefixed = lambda m: f'{m.group(1)}="{prefix}--{m.group(2)}"'  # noqa: E731  (one-line substitution)
    for position, token in enumerate(tokens):
        if token.type == "heading_open":
            token.attrSet("id", f"{prefix}--{heading_anchor(tokens[position + 1].content, seen)}")
        elif token.type == "html_block":
            token.content = HTML_ANCHOR.sub(prefixed, token.content)
        for child in token.children or []:
            if child.type == "html_inline":
                child.content = HTML_ANCHOR.sub(prefixed, child.content)
            elif child.type == "link_open":
                href = assembly.href(str(child.attrGet("href") or ""), source)
                if href is None:
                    child.attrs.pop("href", None)
                else:
                    child.attrSet("href", href)
            elif child.type == "image" and not _external(src := str(child.attrGet("src") or "")):
                image = (source.parent / urllib.parse.unquote(src)).resolve()
                mime = IMAGE_TYPES.get(image.suffix.lower())
                if mime is None or not image.is_file():
                    raise BuildError(
                        f"{_relative_to_cwd(source)}: image '{src}' is missing or not one of {', '.join(IMAGE_TYPES)}"
                    )
                child.attrSet("src", f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode()}")


def _assemble(doc_dir: Path, stamp: Stamp, assembly: _Assembly, work: Path) -> str:
    """The whole document as one self-contained HTML page: the cover, then every section in reading order."""
    md = _markdown()
    parsed: list[tuple[Path, list[Token]]] = []
    blocks: list[Mermaid] = []
    for section in SECTIONS:
        path = (doc_dir / section.file).resolve()
        tokens = md.parse(path.read_text())
        _rewrite(tokens, path, assembly.anchors[path], assembly)
        for token in tokens:
            if _is_mermaid(token):
                blocks.append(Mermaid(path, (token.map or [0])[0] + 1, token.content))
        parsed.append((path, tokens))

    svgs, problems = render_mermaid(blocks, work)
    if problems:
        raise BuildError("a Mermaid block does not render", problems)
    diagrams = iter(enumerate(svgs, start=1))
    body = [_cover(stamp)]
    for number, (path, tokens) in enumerate(parsed):
        for token in tokens:
            if _is_mermaid(token):
                diagram_number, svg = next(diagrams)
                token.type, token.content = "html_block", _diagram(svg, diagram_number)
        css_class = "index" if number == 0 else "section"
        rendered = md.renderer.render(tokens, md.options, {})
        body.append(f'<section id="{assembly.anchors[path]}" class="{css_class}">\n{rendered}</section>')
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(stamp.title)} v{html.escape(stamp.version)}</title>\n<style>\n{STYLESHEET}</style>\n"
        f"</head>\n<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )


def _cover(stamp: Stamp) -> str:
    rows = [
        ("Version", html.escape(stamp.version)),
        ("Status", html.escape(stamp.status)),
        ("Commit", f"<code>{html.escape(stamp.sha)}</code>"),
        ("Date", html.escape(stamp.date)),
        ("Owner", html.escape(stamp.owner)),
    ]
    cells = "\n".join(f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows)
    return (
        f'<section class="cover">\n<h1>{html.escape(stamp.title)}</h1>\n'
        f'<p class="subtitle">arc42 + C4 architecture baseline</p>\n'
        f'<table class="stamp">\n{cells}\n</table>\n'
        f'<p class="frozen">A frozen export of commit <code>{html.escape(stamp.sha[:12])}</code>. Its source is '
        f"<code>docs/architecture/</code> at that commit; the PDF is never edited by hand.</p>\n</section>"
    )


STYLESHEET = """\
@page { size: A4; margin: 18mm 18mm 20mm; }
html { font: 9.5pt/1.45 -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; }
body { margin: 0; }
section.section, section.index { break-before: page; }
section.index > h1:first-child { display: none; }  /* the cover carries the title */
h1 { font-size: 20pt; margin: 0 0 6mm; padding-bottom: 2mm; border-bottom: 1.5pt solid #1f3a5f; color: #1f3a5f; }
h2 { font-size: 13.5pt; margin: 7mm 0 2mm; color: #1f3a5f; }
h3 { font-size: 11pt; margin: 5mm 0 1.5mm; }
h1, h2, h3, h4 { break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1f5fa8; text-decoration: none; }
code { font: 8.5pt "SF Mono", Menlo, Consolas, monospace; background: #f2f4f7; padding: 0 1.5pt; border-radius: 2pt; }
pre { background: #f2f4f7; padding: 3mm; border-radius: 2pt; white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 8.5pt; }
th, td { border: 0.5pt solid #c5ccd6; padding: 1.2mm 2mm; text-align: left; vertical-align: top; }
thead th { background: #e8edf3; }
tr { break-inside: avoid; }
blockquote { margin: 3mm 0; padding: 1mm 4mm; border-left: 2pt solid #c5ccd6; color: #444; }
figure.diagram { margin: 4mm 0; text-align: center; break-inside: avoid; }
figure.diagram svg { max-width: 100%; height: auto; max-height: 230mm; }
img { max-width: 100%; }
section.cover { height: 245mm; display: flex; flex-direction: column; justify-content: center; }
section.cover h1 { font-size: 28pt; border: none; line-height: 1.2; }
section.cover .subtitle { font-size: 13pt; color: #555; margin: 0 0 12mm; }
table.stamp { width: auto; font-size: 11pt; }
table.stamp th { background: #e8edf3; width: 30mm; }
table.stamp td { min-width: 90mm; }
table.stamp code { font-size: 10pt; }
section.cover .frozen { margin-top: 12mm; color: #555; font-size: 9pt; }
"""


def build(doc_dir: Path, out_dir: Path | None = None) -> Path:
    """The PDF of the document at HEAD, with a cover stamped with its version, commit SHA, date and status, exists
    in `out_dir` (default `build/architecture/` at the repository top, which git ignores). The date is the commit's,
    so rebuilding a commit stamps the same cover. Raises BuildError when the working tree is dirty, the document fails
    `check`, the stamp is missing or inconsistent, or `out_dir` lies in the repository but is not git-ignored."""
    doc_dir = doc_dir.resolve()
    top = _clean_repository(doc_dir)
    problems = check(doc_dir, mermaid=False)  # Mermaid is rendered below, once, for the PDF itself
    if problems:
        raise BuildError("the document fails check", problems)
    stamp = _stamp(doc_dir, top)
    anchors = {(doc_dir / section.file).resolve(): Path(section.file).stem for section in SECTIONS}
    assembly = _Assembly(top=top, sha=stamp.sha, github=_github_url(top), anchors=anchors)
    out = (out_dir or top / "build" / "architecture").resolve()
    name = "architecture-document-v" + re.sub(r"[^\w.-]+", "-", stamp.version) + f"-{stamp.sha[:7]}"
    pdf = out / f"{name}.pdf"
    if pdf.is_relative_to(top) and subprocess.run(["git", "-C", str(top), "check-ignore", "-q", str(pdf)]).returncode:
        raise BuildError(f"{_relative_to_cwd(pdf)} would not be git-ignored: the PDF is never committed")
    npx = shutil.which("npx")
    if npx is None:
        raise BuildError("npx not found: build renders Mermaid and prints the PDF with mermaid-cli's Chromium")
    with tempfile.TemporaryDirectory(prefix="architecture-doc-") as tmp:
        work = Path(tmp)
        html_file = work / f"{name}.html"
        html_file.write_text(_assemble(doc_dir, stamp, assembly, work))
        out.mkdir(parents=True, exist_ok=True)
        job = work / "print.json"
        footer = f"{stamp.title} · v{stamp.version} · {stamp.status} · {stamp.sha[:12]}"
        job.write_text(json.dumps({"html": str(html_file), "pdf": str(pdf), "footer": footer, "args": PUPPETEER_ARGS}))
        command = [npx, "--yes", "-p", MERMAID_CLI, "node", str(PRINT_SCRIPT), str(job)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=PRINT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise BuildError(f"printing the PDF timed out after {PRINT_TIMEOUT_SECONDS}s") from None
        if result.returncode != 0 or not pdf.is_file():
            detail = (result.stderr or result.stdout).strip().splitlines()
            raise BuildError(f"printing the PDF failed: {detail[-1] if detail else f'exit {result.returncode}'}")
    return pdf


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
    parser.add_argument("mode", choices=["check", "regenerate", "build"])
    parser.add_argument("--doc-dir", type=Path, default=DOC_DIR, help="the architecture folder (default: %(default)s)")
    parser.add_argument("--no-mermaid", action="store_true", help="check: skip rendering Mermaid blocks")
    parser.add_argument(
        "--out", type=Path, help="build: output folder (default: build/architecture/ in the repository)"
    )
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
    if args.mode == "build":
        try:
            pdf = build(args.doc_dir, args.out)
        except BuildError as error:
            for problem in error.problems:
                print(problem)
            print(f"build refused: {error}")
            return 1
        print(f"built {_relative_to_cwd(pdf)}")
        return 0
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
