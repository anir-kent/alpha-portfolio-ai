"""Seam: the architecture document build command (`scripts/architecture_doc.py`), driven from the outside through its
`check` and `regenerate` modes. Assertions are on the exit status and the reported problems only. Edits are made on
`tmp_path` copies of the document, so the real document is never touched."""

import shutil
from pathlib import Path

import pytest

from scripts.architecture_doc import main

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "architecture"
needs_npx = pytest.mark.skipif(shutil.which("npx") is None, reason="npx is unavailable, so Mermaid cannot be rendered")


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    """A copy of the architecture folder in a mirror of the repo, so its relative links still resolve."""
    mirror = tmp_path / "repo"
    (mirror / "docs").mkdir(parents=True)
    for entry in REPO.iterdir():
        if entry.name != "docs":
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


def test_check_reports_a_broken_relative_link_with_its_file_and_line(doc, capsys):
    edit(doc / "09-architecture-decisions.md", "../adr/0001-deterministic", "../adr/0099-deterministic")

    code, out = run(capsys, "check", "--doc-dir", str(doc), "--no-mermaid")

    assert code == 1
    assert "09-architecture-decisions.md:5: broken link '../adr/0099-deterministic-engine-owns-numbers.md'" in out


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
    edit(doc / "03-context-and-scope.md", "  platform -->|schema-bound calls| llm", "  platform -->|unclosed llm ((")

    code, out = run(capsys, "check", "--doc-dir", str(doc))

    assert code == 1
    assert "03-context-and-scope.md:7: Mermaid block does not render" in out
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
