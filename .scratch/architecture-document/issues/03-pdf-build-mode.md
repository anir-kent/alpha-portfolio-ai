# 03: PDF build mode with stamped cover

**What to build:** The document owner runs the build command in `build` mode and gets a single PDF: Mermaid pre-rendered to SVG, Markdown assembled to HTML in index order with an embedded stylesheet, a cover stamped with version, commit SHA and date, the document-control block, and pages printed through headless Chromium (Puppeteer bundled with mermaid-cli). No pandoc or WeasyPrint. `build` refuses to run on a dirty working tree so the stamped SHA is truthful.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `build` produces a PDF of the current skeleton with all diagrams rendered as vector images
- [ ] Cover shows title, version, commit SHA, date and status; document-control block follows
- [ ] `build` exits non-zero with a clear message on a dirty working tree
- [ ] Generated PDF and intermediate artifacts are git-ignored; only the source is committed
- [ ] Any Python dependency added with `uv add`; manual verification steps noted in the ticket comments
