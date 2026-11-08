"""Regenerates every committed LLM recording, one per model request (ADR-0010; spec: Replay):

    uv run python -m tests.fixtures.regenerate             # go live for any request that has no recording
    uv run python -m tests.fixtures.regenerate --offline   # never go live; a request with no recording fails
    uv run python -m tests.fixtures.regenerate --offline --migrate   # answer from the old format (once, ADR-0010)

In order: the fixture Reports' extraction recordings (`tests.fixtures.llm_cases`, hand-authored replies), then the
seeded demo's Analysis Run, every Suggested Question and the walkthrough (`tests.fixtures.suggested_questions`), which
the assistant eval's Analysis Run replays too. Recordings nothing makes any more are removed. The live assistant eval
(`tests.fixtures.assistant_eval`) records nothing; rerun it by hand before bumping the Assistant's prompt version.
"""

import sys

from tests.fixtures import llm_cases, suggested_questions


def main(argv: list[str]) -> int:
    llm_cases.regenerate()
    return suggested_questions.record(offline="--offline" in argv, migrate="--migrate" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
