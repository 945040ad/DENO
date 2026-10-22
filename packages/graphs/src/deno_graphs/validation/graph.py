"""The validation StateGraph (docs/08 Phase 8).

intake ─► perspective_planner ─► query_planner ─► [Send] collect×source ─► ingest ─► coverage_check
  ├─(sources failed, or a near miss; once)─► broaden ─► [Send] collect×failed/thin source ─► ingest ─► …
  ├─(too little evidence / unclear idea)─► insufficient ─► account ─► finalize
  └─► [Send] analyst×7 ─► citation_validator ─► signal_scorer ─► critic ⇄ refiner (≤2)
        ─► verdict ─► account ─► review (interrupt) ─► finalize
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from deno_graphs.validation import nodes as n
from deno_graphs.validation.state import ValidationState


def build_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    g = StateGraph(ValidationState)
    g.add_node("intake", n.intake)
    g.add_node("perspective_planner", n.perspective_planner)
    g.add_node("query_planner", n.query_planner)
    g.add_node("collect", n.collect)
    g.add_node("ingest", n.ingest)
    g.add_node("coverage_check", n.coverage_check)
    g.add_node("analyst", n.analyst)
    g.add_node("citation_validator", n.citation_validator)
    g.add_node("signal_scorer", n.signal_scorer)
    g.add_node("critic", n.critic)
    g.add_node("refiner", n.refiner)
    g.add_node("verdict", n.verdict)
    g.add_node("insufficient", n.insufficient)
    g.add_node("broaden", n.broaden)
    g.add_node("account", n.account)
    g.add_node("review", n.review)
    g.add_node("finalize", n.finalize)

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", n.route_after_intake, ["perspective_planner", "insufficient"])
    g.add_edge("perspective_planner", "query_planner")
    g.add_conditional_edges("query_planner", n.fan_out_collect, ["collect"])
    g.add_edge("collect", "ingest")
    g.add_edge("ingest", "coverage_check")
    g.add_conditional_edges("coverage_check", n.route_after_coverage, ["analyst", "broaden", "insufficient"])
    g.add_conditional_edges("broaden", n.fan_out_retry, ["collect", "insufficient"])
    g.add_edge("analyst", "citation_validator")
    g.add_edge("citation_validator", "signal_scorer")
    g.add_edge("signal_scorer", "critic")
    g.add_conditional_edges("critic", n.route_after_critic, ["refiner", "verdict"])
    g.add_edge("refiner", "signal_scorer")
    g.add_edge("verdict", "account")
    g.add_edge("insufficient", "account")
    g.add_conditional_edges("account", n.route_after_account, ["review", "finalize"])
    g.add_edge("review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
