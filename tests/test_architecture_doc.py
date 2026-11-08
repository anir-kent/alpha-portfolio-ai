"""Seam: the architecture document build command (`scripts/architecture_doc.py`), driven from the outside through its
`check`, `regenerate` and `build` modes. Assertions are on the exit status, the reported problems and the document text
or, for `build`, the text of the PDF. Edits are made on `tmp_path` copies of the document, so the real document is never
touched. To show that a generated region follows the live code, a test changes the code source itself for one test
(monkeypatching the module attribute the region is generated from: a prompt version, an event type, a default); an
edit to the document could not show that."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import Field
from pypdf import PdfReader

from app import audit, config_service, prompts, settings
from scripts.architecture_doc import main

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "architecture"
# Mermaid rendering needs Node. CI renders it once, in the frontend job's `check` step, so the backend job sets
# SKIP_MERMAID_TESTS=1 rather than rendering again here.
needs_npx = pytest.mark.skipif(
    shutil.which("npx") is None or os.environ.get("SKIP_MERMAID_TESTS") == "1",
    reason="npx is unavailable or SKIP_MERMAID_TESTS=1, so Mermaid is not rendered here",
)


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    """A copy of the architecture folder in a mirror of the repo, so its relative links still resolve."""
    mirror = tmp_path / "repo"
    (mirror / "docs").mkdir(parents=True)
    for entry in REPO.iterdir():
        if entry.name not in ("docs", ".git"):  # never let a test touch the real repository
            (mirror / entry.name).symlink_to(entry)
    for entry in (REPO / "docs").iterdir():
        if entry.name != "architecture":
            (mirror / "docs" / entry.name).symlink_to(entry)
    shutil.copytree(DOC, mirror / "docs" / "architecture")
    return mirror / "docs" / "architecture"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_check_passes_on_the_real_document(capsys):
    code, out = run(capsys, "check", "--doc-dir", str(DOC), "--no-mermaid")
    assert code == 0, out


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new, 1))


def test_check_reports_a_generated_region_that_no_longer_matches_the_code(doc, capsys):
    edit(doc / "08-crosscutting-concepts.md", "| `audit:read` |", "| `audit:read:everything` |")

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "08-crosscutting-concepts.md" in out
    assert "stale generated region 'rbac-matrix'" in out


def test_regenerate_makes_a_stale_document_pass_check_and_leaves_everything_outside_the_markers_byte_identical(
    doc, capsys
):
    section = doc / "08-crosscutting-concepts.md"
    edit(section, "| `audit:read` |", "| `audit:read:everything` |")
    edit(section, "## 8.9 PII stance", "## 8.9 PII stance\r\n\r\nHand-written prose, CRLF and trailing space.  ")
    before = section.read_bytes()
    begin, end = b"<!-- BEGIN GENERATED: rbac-matrix -->", b"<!-- END GENERATED: rbac-matrix -->"

    assert run(capsys, "regenerate", "--doc-dir", str(doc))[0] == 0

    after = section.read_bytes()
    assert after.split(begin)[0] == before.split(begin)[0]
    assert after.split(end)[1] == before.split(end)[1]
    assert after != before
    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")
    assert code == 0, out


SOURCE_CHANGES = {  # region -> (a change to its source in code, a row only the changed source renders)
    "prompt-versions": (
        lambda mp: mp.setattr(
            prompts,
            "ALL",
            tuple(
                prompts.Prompt(prompt.name, "v-next", prompt.system) if prompt.name == "assistant_answer" else prompt
                for prompt in prompts.ALL
            ),
        ),
        "| `assistant_answer` | `v-next` | `assistant_answer@v-next` |",
    ),
    "audit-event-types": (
        lambda mp: mp.setattr(audit, "EVENT_TYPES", (*audit.EVENT_TYPES, "chain_sealed")),
        "| `chain_sealed` |",
    ),
    "config-defaults": (
        lambda mp: mp.setattr(
            config_service,
            "Config",
            type("Config", (config_service.Config,), {"__annotations__": {"sla_days": int}, "sla_days": 45}),
        ),
        "| `sla_days` | 45 |",
    ),
    "assistant-limits": (
        lambda mp: mp.setattr(
            settings,
            "Settings",
            type(
                "Settings",
                (settings.Settings,),
                {
                    "__annotations__": {"assistant_questions_per_hour": int},
                    "assistant_questions_per_hour": Field(10, description="Questions an hour"),
                },
            ),
        ),
        "| `APP_ASSISTANT_QUESTIONS_PER_HOUR` | 10 |",
    ),
}


@pytest.mark.parametrize("region", SOURCE_CHANGES)
def test_a_code_change_behind_a_generated_region_fails_check_until_regenerated(region, doc, monkeypatch, capsys):
    change, new_row = SOURCE_CHANGES[region]
    change(monkeypatch)

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")
    assert code == 1
    assert f"stale generated region '{region}'" in out

    assert run(capsys, "regenerate", "--doc-dir", str(doc))[0] == 0
    assert new_row in (doc / "08-crosscutting-concepts.md").read_text()
    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")
    assert code == 0, out


def test_check_reports_a_broken_relative_link_with_its_file_and_line(doc, capsys):
    edit(doc / "09-architecture-decisions.md", "../adr/0001-deterministic", "../adr/0099-deterministic")

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "09-architecture-decisions.md:7: broken link '../adr/0099-deterministic-engine-owns-numbers.md'" in out


def test_check_reports_a_link_to_a_heading_that_does_not_exist(doc, capsys):
    edit(doc / "13-roadmap.md", "#103-non-goals", "#103-goals-we-dropped")

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "broken anchor '10-quality-requirements.md#103-goals-we-dropped'" in out


def test_check_reports_a_missing_section_file_and_a_missing_required_heading(doc, capsys):
    (doc / "11-risks-and-technical-debt.md").unlink()
    edit(doc / "06-runtime-view.md", "## 6.2 Tiered Decisions", "## 6.2 Approvals")

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "11-risks-and-technical-debt.md:0: missing section file" in out
    assert "06-runtime-view.md:0: missing required heading '6.2 Tiered Decisions'" in out


def test_check_reports_an_index_that_skips_a_section(doc, capsys):
    edit(doc / "index.md", "7. [6. Runtime View](06-runtime-view.md)\n", "")

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "index does not link section '06-runtime-view.md'" in out


@needs_npx
def test_check_renders_every_mermaid_block_in_the_real_document(capsys):
    code, out = run(capsys, "check", "--doc-dir", str(DOC))
    assert code == 0, out


@needs_npx
def test_check_reports_a_mermaid_block_that_does_not_render(doc, capsys):
    edit(doc / "03-context-and-scope.md", "  class platform system", "  platform -->|unclosed llm ((")

    code, out = run(capsys, "check", "--doc-dir", str(doc))

    assert code == 1
    assert "03-context-and-scope.md:9: Mermaid block does not render" in out
    assert "unclosed llm ((" in out  # names the offending diagram source, not just a line number


def test_check_reports_a_mistyped_marker_instead_of_silently_ignoring_the_region(doc, capsys):
    edit(
        doc / "08-crosscutting-concepts.md", "<!-- END GENERATED: rbac-matrix -->", "<!-- END GENERATED rbac-matrix -->"
    )

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "malformed generated-region marker '<!-- END GENERATED rbac-matrix -->'" in out
    assert "generated region 'rbac-matrix' is not closed" in out


def test_regenerate_fixes_a_stale_region_in_a_file_saved_with_windows_line_endings(doc, capsys):
    section = doc / "08-crosscutting-concepts.md"
    edit(section, "| `audit:read` |", "| `audit:read:everything` |")
    section.write_bytes(section.read_bytes().replace(b"\n", b"\r\n"))
    assert run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")[0] == 1

    assert run(capsys, "regenerate", "--doc-dir", str(doc))[0] == 0

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")
    assert code == 0, out
    assert b"## 8.9 PII stance\r\n" in section.read_bytes()


def git(repo: Path, *args: str) -> str:
    command = ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", *args]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def committed_doc(doc: Path) -> Path:
    """The `doc` copy, committed as the only commit of a fresh repository, so its working tree is clean."""
    repo = doc.parents[1]
    git(repo, "init", "--quiet")
    git(repo, "add", "--all")
    git(repo, "commit", "--quiet", "-m", "baseline")
    return doc


def test_build_refuses_a_dirty_working_tree_so_the_stamped_sha_matches_the_content(committed_doc, tmp_path, capsys):
    section = committed_doc / "04-solution-strategy.md"
    section.write_text(section.read_text() + "\nAn uncommitted edit.\n")

    code, out = run(capsys, "build", "--doc-dir", str(committed_doc), "--out", str(tmp_path / "out"))

    assert code == 1
    assert "working tree is dirty" in out
    assert "docs/architecture/04-solution-strategy.md" in out
    assert not (tmp_path / "out").exists()


def test_build_refuses_a_cover_status_that_the_version_history_row_contradicts(committed_doc, tmp_path, capsys):
    edit(committed_doc / "index.md", "| Status | Draft |", "| Status | Under ARB Review |")
    git(committed_doc.parents[1], "commit", "--quiet", "--all", "-m", "status changed, history row not")

    code, out = run(capsys, "build", "--doc-dir", str(committed_doc), "--out", str(tmp_path / "out"))

    assert code == 1
    assert "Document control says Status 'Under ARB Review' but the Version history row" in out
    assert not (tmp_path / "out").exists()


@needs_npx
def test_build_prints_a_pdf_with_the_stamped_cover_and_the_diagrams_as_vector_text(committed_doc, tmp_path, capsys):
    repo = committed_doc.parents[1]
    diagram = "\n```mermaid\nflowchart LR\n  owner -->|signs the stamped baseline| board\n```\n"
    (committed_doc / "04-solution-strategy.md").write_text(
        (committed_doc / "04-solution-strategy.md").read_text() + diagram
    )
    git(repo, "commit", "--quiet", "--all", "-m", "a diagram")
    sha = git(repo, "rev-parse", "HEAD")

    code, out = run(capsys, "build", "--doc-dir", str(committed_doc), "--out", str(tmp_path / "out"))

    assert code == 0, out
    [pdf] = (tmp_path / "out").glob("*.pdf")
    reader = PdfReader(pdf)
    cover = " ".join(reader.pages[0].extract_text().split())  # pypdf breaks lines where Chromium wrapped them
    assert "Portfolio Rebalancing: Architecture Document" in cover
    assert sha in cover
    assert "Version 0.0" in cover
    assert "Status Draft" in cover
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Document control" in text
    assert "signs the stamped baseline" in text  # a Mermaid edge label as extractable text: vector, not raster
    assert "flowchart LR" not in text  # no diagram left as source
