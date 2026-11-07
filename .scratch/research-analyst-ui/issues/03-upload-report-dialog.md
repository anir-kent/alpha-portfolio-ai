# 03: Upload a Report and land on it

**What to build:** A Research Analyst clicks **Upload Report** in the Research page header and a dialog opens. They pick or drag and drop a PDF or plain-text file and optionally give a title (defaulting to the file name). The browser rejects other file types and anything over 20 MB, matching the server limit, before sending. While the upload runs, the dialog shows "Extracting Insights from your Report…", disables its controls and cannot be dismissed by accident, because extraction happens inside the request. On success the dialog closes and the Analyst lands on the new Report's detail (ticket 02), with its Insights awaiting review. A 413 or 422 from the server shows inline in the dialog. A Report that comes back with failed extraction lands on its detail showing the stored error and an **Upload again** action that reopens the dialog.

This is the first ticket that produces Insights awaiting review through the UI. In recorded LLM mode (the default), uploading the demo house view from the test fixtures replays the committed extraction recording; a file with no recording exercises the failed-extraction path.

See spec: Upload dialog; Access.

**Blocked by:** 02

**Status:** resolved

- [x] The Upload Report action is shown only with the `report:upload` permission
- [x] The dialog accepts a picked or dropped PDF or plain-text file; other types and files over 20 MB are rejected in the browser with a specific message, before any request
- [x] The title is optional and defaults to the file name
- [x] During the request the dialog shows the extracting state, disables its controls, and Escape or a backdrop click does not close it
- [x] On success the Report list is refreshed and the Analyst is taken to the new Report's detail
- [x] 413 and 422 responses are shown inline in the dialog with the server's message, and the Analyst can pick another file and retry
- [x] A Report returned with failed extraction lands on its detail with the stored error and an Upload again action
- [x] The dialog manages focus: focus moves into it on open, is trapped while open, and returns to the Upload Report button on close
- [x] The Research Analyst checklist section gains: upload the demo house view and land on it with Insights awaiting review; upload an unsupported file type; upload a file over 20 MB; upload a file with no recording (recorded mode) and see the failed state with Upload again
- [x] Typecheck, lint, format check and build pass
