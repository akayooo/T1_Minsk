"""Определение графа обработки запросов."""

import logging
from typing import Any, Callable, Dict, Literal

from langgraph.graph import StateGraph

from .state import AgentState

logger = logging.getLogger(__name__)


def build_graph(
    *,
    finder_node: Callable[[Dict[str, Any]], Dict[str, Any]],
    rag_node: Callable[[Dict[str, Any]], Dict[str, Any]],
    memory_node: Callable[[Dict[str, Any]], Dict[str, Any]],
    reranker_node: Callable[[Dict[str, Any]], Dict[str, Any]],
    controller_node: Callable[[Dict[str, Any]], Dict[str, Any]] = None,
    hints_generator_node: Callable[[Dict[str, Any]], Dict[str, Any]],
    validator_node: Callable[[Dict[str, Any]], Dict[str, Any]] = None,
    should_continue_after_controller: Callable[[Dict[str, Any]], Literal["finder", "hints_generator"]] = None,
    should_continue_after_validation: Callable[[Dict[str, Any]], Literal["hints_generator", "__end__"]] = None,
) -> StateGraph:
    """Строит граф рабочего процесса агентов поддержки."""
    logger.info("Построение графа рабочего процесса агентов поддержки...")

    workflow = StateGraph(AgentState)

    workflow.add_node("finder", finder_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("memory", memory_node)
    workflow.add_node("reranker", reranker_node)
    
    if controller_node:
        workflow.add_node("controller", controller_node)
        
    workflow.add_node("hints_generator", hints_generator_node)
    
    if validator_node:
        workflow.add_node("validator", validator_node)

    workflow.set_entry_point("finder")

    workflow.add_edge("finder", "memory")
    workflow.add_edge("finder", "rag")
    workflow.add_edge("rag", "reranker")
    
    if controller_node and should_continue_after_controller:
        workflow.add_edge("reranker", "controller")
        workflow.add_conditional_edges(
            "controller",
            should_continue_after_controller,
            {
                "finder": "finder",
                "hints_generator": "hints_generator"
            }
        )
    else:
        workflow.add_edge("reranker", "hints_generator")

    if validator_node and should_continue_after_validation:
        workflow.add_edge("hints_generator", "validator")
        workflow.add_conditional_edges(
            "validator",
            should_continue_after_validation,
            {
                "hints_generator": "hints_generator",
                "__end__": "__end__"
            }
        )
    else:
        # Прямой переход от hints_generator к концу
        workflow.add_edge("hints_generator", "__end__")

    app = workflow.compile()
    logger.info("Граф рабочего процесса с контроллером успешно скомпилирован")
    return app
