Status: done
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
- [x] One commit for this ticket
- [x] APIs checked via Context7 (current RAGAS LangChain wrappers)
- [x] The main install and test suite don't need `ragas`
- [x] A sample report is produced once live

## Findings (run 2026-11-20, live; judge `anthropic/claude-sonnet-5.5`, ragas 0.4.4)

Report: `.scratch/rag-insight-extraction/ragas.md` (`uv run --extra eval python -m scripts.eval_ragas`). 19 labelled views.

| Metric | Mean |
| --- | --- |
| faithfulness | 0.809 (n=15) |
| context precision (with reference) | 0.974 (n=19) |
| context recall | 0.842 (n=19) |

- Precision is near the ceiling. Recall's misses are Fidelity's Communication Services and Financials (views no path found) and one UBS bond view.
- Faithfulness is lower on Fidelity table rows (0.33 to 0.50). The response is a sentence built around the quoted passage, so some of that may be the rendering, not the model. The judge is the same model as the extractor (self-judging bias).
- The ticket's `get_chat_model("eval")` does not exist: `get_chat_model(settings)` is used. `LangchainLLMWrapper` needs `bypass_temperature=True` (Claude 5 via OpenRouter rejects a temperature). ragas 0.4 deprecates the LangChain wrappers in favour of its own client factories; they still work and are what the ticket asked for.
