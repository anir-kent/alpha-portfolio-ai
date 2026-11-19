Status: resolved
Blocked by: 01

# Assistant graph: agent, tools and validate nodes with one lookup

## What to build
Build the Assistant as a `StateGraph` following LangGraph's documented tool-calling agent pattern:
- an `agent` node with `model.bind_tools(tools)`, using the model from `get_chat_model`;
- a prebuilt `ToolNode` named `tools`;
- a conditional edge `agent → tools | validate`, and an edge `tools → agent`;
- a `validate` node, which passes through to END in this ticket.

Start with one read-only lookup (tracer bullet). It is an `@tool` wrapping the existing permission-checked builder, with its argument schema taken from the existing Pydantic models. Conversation and Screen Context handling stay unchanged. The trajectory summary for 'How I answered' is derived from the Exchanges, as today.

Check the APIs against current docs via Context7.

## Acceptance criteria
- [x] A Question needing one lookup is answered with a two-request Trajectory: `agent`, then `tools`, then `agent`
- [x] 'How I answered' shows the lookup, its arguments, the summary, the request count and the token count
- [x] A Suggested Question is answered live (the same path as any Question: no replay), and a scripted fake-model test covers the same path offline (`test_a_question_needing_one_lookup_is_a_two_request_agent_tools_agent_trajectory`). Live smoke not run: no API key in this session
