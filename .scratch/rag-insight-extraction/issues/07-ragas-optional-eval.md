Status: ready-for-agent
Blocked by: 06

# Optional RAGAS evaluation script

## What to build
- `ragas` goes in an optional dependency group (`uv add --optional eval ragas`).
- `scripts/eval_ragas.py`:
  - runs the extraction graph on the labelled set;
  - scores faithfulness, context precision and context recall, using a judge from `get_chat_model("eval")` and the app's embeddings;
  - writes a report file.
- Its calls are not Exchanges and are not audited. Say so in the script's docstring and the README.

## Acceptance criteria
- [ ] One commit for this ticket
- [ ] APIs checked via Context7 (current RAGAS LangChain wrappers)
- [ ] The main install and test suite don't need `ragas`
- [ ] A sample report is produced once live
