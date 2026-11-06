"""LangGraph workflow: build a constrained prompt, optionally generate, stop at human review.

The graph is pure: it reads a release snapshot and returns results. The API applies those
results to the database through the state machine, so no node can approve anything.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .generator import GenerationDisabled, Generator, GeneratorError
from .prompting import build_prompt


class WorkflowState(TypedDict, total=False):
    lane: str
    brief: str
    bpm: int | None
    musical_key: str | None
    duration_s: int
    template_tags: str
    bpm_range: tuple[int | None, int | None]
    seed: int | None
    generation_enabled: bool
    prompt: str
    warnings: list[str]
    audio_path: str | None
    audio_url: str | None
    generation_metadata: dict[str, Any]
    error: str | None
    outcome: str  # "review" or "failed"


def build_workflow(generator: Generator):
    def prepare_prompt(state: WorkflowState) -> WorkflowState:
        try:
            result = build_prompt(
                lane=state.get("lane", ""),
                brief=state.get("brief", ""),
                bpm=state.get("bpm"),
                musical_key=state.get("musical_key"),
                duration_s=state.get("duration_s", 180),
                template_tags=state.get("template_tags", ""),
                bpm_range=state.get("bpm_range", (None, None)),
            )
        except ValueError as exc:
            return {"error": str(exc), "warnings": []}
        return {"prompt": result.prompt, "warnings": result.warnings, "error": None}

    def generate(state: WorkflowState) -> WorkflowState:
        try:
            result = generator.generate(
                state["prompt"], state.get("duration_s", 180), state.get("seed")
            )
        except GenerationDisabled:
            return {"warnings": [*state.get("warnings", []), "generation skipped: disabled"]}
        except GeneratorError as exc:
            return {"error": f"generation failed: {exc}"}
        return {
            "audio_path": result.audio_path,
            "audio_url": result.audio_url,
            "generation_metadata": result.metadata,
        }

    def human_review(state: WorkflowState) -> WorkflowState:
        # Terminal node: the workflow parks the release for a person to decide.
        return {"outcome": "failed" if state.get("error") else "review"}

    def after_prompt(state: WorkflowState) -> str:
        if state.get("error"):
            return "human_review"
        return "generate" if state.get("generation_enabled") else "human_review"

    graph = StateGraph(WorkflowState)
    graph.add_node("prepare_prompt", prepare_prompt)
    graph.add_node("generate", generate)
    graph.add_node("human_review", human_review)
    graph.add_edge(START, "prepare_prompt")
    graph.add_conditional_edges("prepare_prompt", after_prompt, ["generate", "human_review"])
    graph.add_edge("generate", "human_review")
    graph.add_edge("human_review", END)
    return graph.compile()
