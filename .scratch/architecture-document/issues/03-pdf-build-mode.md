# 03: PDF build mode with stamped cover

**What to build:** The document owner runs the build command in `build` mode and gets a single PDF: Mermaid pre-rendered to SVG, Markdown assembled to HTML in index order with an embedded stylesheet, a cover stamped with version, commit SHA and date, the document-control block, and pages printed through headless Chromium (Puppeteer bundled with mermaid-cli). No pandoc or WeasyPrint. `build` refuses to run on a dirty working tree so the stamped SHA is truthful.

**Blocked by:** 01

**Status:** resolved

- [x] `build` produces a PDF of the current skeleton with all diagrams rendered as vector images
- [x] Cover shows title, version, commit SHA, date and status; document-control block follows
- [x] `build` exits non-zero with a clear message on a dirty working tree
- [x] Generated PDF and intermediate artifacts are git-ignored; only the source is committed
- [x] Any Python dependency added with `uv add`; manual verification steps noted in the ticket comments

## Comments

**2026-11-07, implementation (Claude).** Commit a524c94.
- `uv run python -m scripts.architecture_doc build [--out DIR]` writes `build/architecture/architecture-document-v<version>-<sha7>.pdf`. `build/` is git-ignored, and an `--out` inside the repo that git would not ignore is refused. The assembled HTML stays in a temp folder.
- Pipeline: mermaid-cli renders every Mermaid block to SVG in one batch. markdown-it-py (dev dependency, `uv add --dev`) assembles the sections in `SECTIONS` order into one HTML page with an embedded stylesheet. `scripts/architecture_doc_print.mjs` prints it through the Puppeteer bundled with mermaid-cli (`npx -p @mermaid-js/mermaid-cli@12.2.0 node ...`). No pandoc, no WeasyPrint.
- The stamp is read from `docs/architecture/index.md`:
  - **version**: the first cell of the last Version history row;
  - **status** and **owner**: the Document control table;
  - **SHA**: HEAD;
  - **date**: the commit date, so rebuilding a commit gives the same cover.
- The cover is followed by the document-control block, then every section on a new page. Each page has a footer with title, version, status, SHA and page number. Headings become PDF bookmarks.
- Links between sections become in-PDF links. Links leaving the document (ADRs, `GLOSSARY.md`) point at GitHub pinned to the stamped commit, so they 404 until that commit is pushed.
- `build` refuses:
  - a dirty working tree (untracked files included), listing the changes;
  - a document that fails `check`;
  - a missing stamp field;
  - a Document control Status that differs from the Status of the last Version history row.
- Tests (seam: `main(["build", ...])`):
  - dirty-tree refusal and status mismatch, which need no Chromium and run in CI;
  - a full PDF build from a clean temp repository, read back with pypdf. It needs npx, so CI skips it, as the spec says.

**For ticket 14 (v0.1 export).** A version-history row cannot hold the SHA of the commit that adds it. Commit the row with `(this export)` in Commit and the export's status (it must equal Document control's Status), then build. Fill in the SHA from the cover in a later commit; the next export's cover carries that commit.

**Manual verification per release** (the spec keeps build out of CI):
1. Commit everything (`git status` empty), then `uv run python -m scripts.architecture_doc build`.
2. Open the PDF and check:
   - the cover shows title, version, status, the full SHA matching `git rev-parse HEAD`, the date and the owner;
   - page 2 is the document-control block;
   - each Mermaid diagram is sharp when zoomed (vector);
   - the generated RBAC table is present;
   - the Contents links jump to their sections.
3. `git status` is still clean (the PDF is ignored).

**Verified 2026-11-07:**
- A real build on a clean tree at a524c94 printed 20 pages. The cover reads `Commit a524c941fd84480e1f7342c499f9d04ed031f03b`, with 50 internal links and 11 GitHub links pinned to that SHA. The tree stayed clean afterwards.
- The real build on a dirty tree exited 1 and listed the changes.
- I inspected a test build's pages visually: cover, document control, C4 System Context diagram.
- pytest 629 passed, 1 skipped (before the review fixes); `tests/test_architecture_doc.py` 14 passed after them.
- ruff, ruff format, mypy and pre-commit clean.

**Code review, left open:**
- `check` reads Markdown with its own reader, while `build` uses markdown-it. They could disagree on setext headings or on fences nested in lists. Worth unifying on markdown-it in a later ticket.
- `architecture_doc.py` now holds check, regenerate and build. If it grows further, split the build section into its own module.
