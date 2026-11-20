"""The pipeline's LLM Graph (ADR-0011): one compiled `StateGraph` behind the step-facing `complete`, shared by Insight
extraction, Research Tilt proposal, the Recommendation narrative and the priority narrative.

It is LangGraph's documented workflow pattern at its smallest: typed state, one Graph Node `generate`, START →
generate → END. The node makes one model call, `model.with_structured_output(<reply schema>, method="json_schema",
include_raw=True)`, on the step's system and user messages. There is no retry edge: an unparseable reply or one that is
not a JSON object raises `LlmError`, and the step's own failure outcome handles it. The step's Pydantic model still
validates the reply afterwards. The chat model is runtime context, so the one compiled graph serves every call and every
test double.
"""

import json
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.llm import LlmError, LlmRequest, wire_schema

GENERATE = "generate"
# The step's system text carries its reply schema, as its prompt always has (ADR-0007).
REPLY_SCHEMA_HEADING = "\n\nJSON schema of the reply:\n"


class PipelineState(TypedDict):
    request: LlmRequest
    content: NotRequired[dict]


@dataclass(frozen=True)
class PipelineContext:
    model: BaseChatModel


def system_prompt(request: LlmRequest) -> str:
    return request.system + REPLY_SCHEMA_HEADING + json.dumps(request.schema)


def generate(state: PipelineState, runtime: Runtime[PipelineContext]) -> dict:
    """The reply object of one model call for the state's request, held to its schema by native structured output."""
    request = state["request"]
    # Named after the task: the provider's schema name, and what an Exchange's reader sees in the request.
    schema = {**wire_schema(request.schema), "title": request.task}  # type: ignore[dict-item]
    model = runtime.context.model.with_structured_output(schema, method="json_schema", include_raw=True)
    result = model.invoke([SystemMessage(system_prompt(request)), HumanMessage(request.user)])
    if result["parsing_error"] is not None:  # type: ignore[index]
        raise LlmError(f"LLM reply was not valid JSON: {result['parsing_error']}")  # type: ignore[index]
    if not isinstance(result["parsed"], dict):  # type: ignore[index]
        raise LlmError("LLM reply was not a JSON object")
    return {"content": result["parsed"]}  # type: ignore[index]


PIPELINE = (
    StateGraph(PipelineState, context_schema=PipelineContext)
    .add_node(GENERATE, generate)
    .add_edge(START, GENERATE)
    .add_edge(GENERATE, END)
    .compile(name="pipeline")
)


def run_pipeline(model: BaseChatModel, request: LlmRequest, callbacks: list[BaseCallbackHandler]) -> dict:
    """The reply object for `request`, from one run of the pipeline graph on `model`. `callbacks` see the model call;
    its run metadata names the step's task and prompt version."""
    state = PIPELINE.invoke(
        {"request": request},
        {
            "callbacks": callbacks,
            "metadata": {"llm_task": request.task, "llm_prompt_version": request.prompt_version},
        },
        context=PipelineContext(model=model),
    )
    return state["content"]
