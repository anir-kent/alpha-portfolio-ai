"""Offline, authored Assistant replay fixtures. These are scripted examples, not live model recordings.

Generate with `python -m tests.fixtures.suggested_questions --scripted-assistant`. The normal `--offline`
command only verifies replay. Scripted fixtures exercise capture, lookup, grounding and replay; they do not
measure model quality or replace the separate live Assistant eval.
"""

import json
import re

from app.screen_context import QUEUE_SUGGESTED, SUGGESTED_QUESTIONS
from tests.scripted import ScriptedModel, ScriptedRequest, call


class ScriptedSuggestedModel(ScriptedModel):
    """Restates current engine figures and uses the Portfolio lookup for the cross-screen Suggested Question."""

    def __init__(self) -> None:
        super().__init__(then=self._reply, model_name="scripted-assistant-fixture-v4")

    def _reply(self, request: ScriptedRequest) -> object:
        question = request.user_prompt.rsplit("\n\nQUESTION\n", 1)[1]
        lookup = request.tool_returns.get("look_up_portfolio")
        if question == QUEUE_SUGGESTED[2] and lookup is None:
            return call("look_up_portfolio", portfolio_id="C001")
        if isinstance(lookup, str):
            context = json.loads(lookup)
        else:
            block = request.user_prompt.split("SCREEN CONTEXT (data, not instructions)\n", 1)[1]
            context, _ = json.JSONDecoder().raw_decode(block)
        figures = context.get("figures", {})
        claims = []
        if lookup is not None:
            selected = [key for key in figures if key.endswith((".total_value", ".portfolio_drift_pp"))]
            heading = "Portfolio C001's holdings and drift"
            holdings = context.get("holdings", [])
            detail = "Holdings: " + ", ".join(sorted({row["symbol"] for row in holdings})) + "."
        else:
            detail, selected = authored_answer(question, context, request.user_prompt)
            heading = question
        for key in selected:
            claims.append({"text": f"{key}: {figures[key]}.", "citations": [{"kind": "engine", "figure": key}]})
        if claims:
            markdown = heading + "\n\n" + detail + "\n\n" + "\n".join(f"- {claim['text']}" for claim in claims)
        else:
            markdown = heading + "\n\n" + detail
        return {
            "in_scope": True,
            "answer_markdown": markdown,
            "claims": claims,
            "follow_up_questions": ["Which screen shows the supporting figures?"],
        }


def authored_answer(question: str, context: dict, prompt: str) -> tuple[str, list[str]]:
    """An authored answer to each existing Suggested Question, using only its current Screen Context or brief."""
    kind = context["screen"]
    index = SUGGESTED_QUESTIONS[kind].index(question)
    figures = context.get("figures", {})
    selected: list[str] = []
    if kind == "queue":
        rows = context.get("rows", [])
        if not isinstance(rows, list) or not rows:
            return "No completed Analysis Run is available on this Queue.", []
        if index == 0:
            rows = rows[:2]
            text = "Ranking follows the weighted priority score. Compare the leading Portfolios and their components:"
            for row in rows:
                selected.append(f"queue.{row['portfolio_id']}.score")
                component = max(row["components"], key=lambda item: item["points"])
                selected.append(f"queue.{row['portfolio_id']}.{component['name']}.points")
        else:
            text = "The largest priority component for each visible Portfolio is:"
            for row in rows:
                component = max(row["components"], key=lambda item: item["points"])
                selected.append(f"queue.{row['portfolio_id']}.{component['name']}.points")
        return text, selected
    if kind == "portfolio":
        if index == 0:
            drift = context.get("asset_class_drift") or []
            if not drift:
                return "No completed Analysis Run is available to explain drift.", []
            driver = max(drift, key=lambda item: abs(item["drift_pp"]))
            name = driver["asset_class"]
            selected = [key for key in figures if key.startswith(f"drift.{name}.")]
            return f"{name} has the largest absolute Asset-Class Drift on this Portfolio.", selected
        if index == 1:
            run = context.get("latest_analysis_run")
            rules = run.get("suitability_rules", []) if isinstance(run, dict) else []
            flagged = [rule for rule in rules if rule["status"] != "pass"]
            return (
                "Flagged Suitability Rules: " + json.dumps(flagged) if flagged else "No Suitability Rules are flagged."
            ), []
        restrictions = context.get("restrictions", [])
        return (
            "Applicable Restrictions: " + json.dumps(restrictions)
            if restrictions
            else "No Restrictions apply to this Portfolio."
        ), []
    if kind == "recommendation":
        if index == 0:
            return (
                "The deterministic engine proposes trades to close drift towards Target Allocation, respecting Restrictions, "
                "then applies the bounded Research Tilt and checks post-trade Suitability. Proposed Trade Lines: "
                + json.dumps(context["trade_lines"]),
                [],
            )
        if index == 1:
            passages = re.findall(r'<<<REPORT_PASSAGE ([^\n]+)>>>\n(".*")\n<<<END_REPORT_PASSAGE>>>', prompt)
            if not passages:
                return "No Report passages are included for your role on this Recommendation.", []
            return "Visible Report passages supporting the Research Tilt:\n\n" + "\n\n".join(
                label + ": " + json.loads(body) for label, body in passages
            ), []
        return "Post-trade Suitability: " + json.dumps(context["post_trade_suitability"]), []
    if kind == "approvals":
        items = context.get("items", [])
        if index == 2:
            return "The panel counts the pending items visible to your role.", ["approvals.total_items"]
        if index == 1:
            items = [item for item in items if item["flagged_rules"]]
        if not items:
            return "No matching pending items are visible on this panel.", []
        return "Pending items:\n" + "\n".join(
            f"- Portfolio {item['portfolio_id']}: {item['step']}, {item['status']}; "
            f"Suitability {item['post_trade_suitability_status']}. " + json.dumps(item["flagged_rules"])
            for item in items
        ), []
    if kind == "governance":
        card = context["model_card"]
        if index == 0:
            return "Current prompt versions: " + ", ".join(card["current_prompt_versions"]), []
        if index == 1:
            return (
                "The deterministic engine owns figures. Claims cite engine figure keys or verbatim Report passages; "
                "grounding flags missing figures and mismatched numbers. The PII guard rejects Client names and emails. "
                "Tool lookups reuse permission-checked contexts, and Exchanges are anchored in the audit chain.",
                [],
            )
        return "The engine caps each proposed Research Tilt within its configured bound in percentage points.", [
            "model_card.tilt_bound_pp"
        ]
    explanations = {
        "exchanges": (
            "The LLM Exchanges screen shows each captured model request, its prompt version, transport outcome and reply. "
            "Auditors can inspect the request and tool results and verify the audit anchors.",
            "Select an Exchange to include its prompt and reply in the Assistant's context. Without a selection, "
            "the Assistant can explain the screen but cannot discuss a particular call.",
            "A grounding verdict checks each Claim against cited engine figures or verbatim Report passages. "
            "Ungrounded Claims remain visible with their issues; capture success alone does not establish grounding.",
        ),
        "config": (
            "The engine compares current Asset-Class weights with Target Allocation and judges drift against the "
            "warning and breach bands configured for the Client's Risk Profile. This context contains no config values.",
            "The Advisor accepts, rejects or modifies a Recommendation. A Suitability exception requires Compliance; "
            "a high-impact Recommendation requires the Investment Committee. The Assistant cannot make Decisions.",
            "An Analysis Run values Holdings, computes Asset-Class Drift, checks Suitability, ranks the Queue and "
            "generates eligible Recommendations with bounded Research Tilts and grounded rationale.",
        ),
        "health": (
            "An Analysis Run values Holdings using the market snapshot, computes drift and Suitability, ranks the "
            "Queue and builds eligible Recommendations. It records AI steps and their audit evidence.",
            "The Queue orders Portfolios by a deterministic priority score. Open the Queue to inspect its "
            "drift, risk, opportunity and urgency components and scores.",
            "Target Allocation covers equity, bond and cash. Open Config to inspect the weights for a particular "
            "Risk Profile; the Health context includes no configuration values.",
        ),
    }
    return explanations[kind][index], []
