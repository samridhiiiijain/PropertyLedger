from __future__ import annotations

from typing import TypedDict

from ..selection.evidence_planner import EvidencePlanner
from ..selection.question_analyzer import QuestionAnalyzer
from ..selection.selection_models import (
    AnalyzedQuestion,
    EvidenceSelectionPlan,
    SelectionStatus,
)
from .plan_validator import WorkflowPlanValidator
from .source_executor import WorkflowSourceExecutor
from .workflow_models import (
    WorkflowAnswerResponse,
    WorkflowEvidence,
    WorkflowExecutionResult,
    WorkflowStateSnapshot,
    WorkflowStatus,
    WorkflowStepName,
    WorkflowStepStatus,
    WorkflowTraceStep,
    WorkflowValidationResult,
)


class WorkflowState(TypedDict, total=False):
    question: str
    analysis: AnalyzedQuestion
    plan: EvidenceSelectionPlan
    validation: WorkflowValidationResult
    execution: WorkflowExecutionResult
    answer: str
    evidence: tuple[WorkflowEvidence, ...]
    status: WorkflowStatus
    trace: tuple[WorkflowTraceStep, ...]


class LangGraphWorkflow:
    """Run the Day 8 evidence workflow through a validated LangGraph state machine."""

    def __init__(
        self,
        analyzer: QuestionAnalyzer | None = None,
        planner: EvidencePlanner | None = None,
        validator: WorkflowPlanValidator | None = None,
        executor: WorkflowSourceExecutor | None = None,
    ) -> None:
        self.analyzer = analyzer or QuestionAnalyzer()
        self.planner = planner or EvidencePlanner(analyzer=self.analyzer)
        self.validator = validator or WorkflowPlanValidator()
        if executor is None:
            raise ValueError("WorkflowSourceExecutor must be provided by application startup.")
        self.executor = executor
        self._graph = self._compile_graph()

    def run(self, question: str) -> WorkflowAnswerResponse:
        if self._graph is None:
            raise RuntimeError(
                "LangGraph is not installed. Install backend requirements before running "
                "the workflow: pip install -r backend/requirements.txt."
            )

        state = self._graph.invoke(
            {
                "question": question,
                "trace": (),
                "evidence": (),
            }
        )
        return self._response_from_state(state)

    def snapshot(self, question: str) -> WorkflowStateSnapshot:
        if self._graph is None:
            raise RuntimeError(
                "LangGraph is not installed. Install backend requirements before running "
                "the workflow: pip install -r backend/requirements.txt."
            )

        state = self._graph.invoke(
            {
                "question": question,
                "trace": (),
                "evidence": (),
            }
        )
        return WorkflowStateSnapshot(
            question=state["question"],
            intent=state.get("plan").intent if state.get("plan") else None,
            plan=state.get("plan"),
            validation=state.get("validation"),
            selected_sources=state.get("plan").selected_sources if state.get("plan") else (),
            evidence=state.get("evidence", ()),
            answer=state.get("answer"),
            status=state.get("status"),
            trace=state.get("trace", ()),
        )

    def _compile_graph(self):
        try:
            from langgraph.graph import END, StateGraph
        except ImportError:
            return None

        graph = StateGraph(WorkflowState)
        graph.add_node("receive_question", self._receive_question)
        graph.add_node("analyze_question", self._analyze_question)
        graph.add_node("build_source_selection_plan", self._build_source_selection_plan)
        graph.add_node("validate_plan", self._validate_plan)
        graph.add_node("execute_selected_source", self._execute_selected_source)
        graph.add_node("return_answer", self._return_answer)
        graph.add_node("reject_request", self._reject_request)
        graph.add_node("show_trace", self._show_trace)

        graph.set_entry_point("receive_question")
        graph.add_edge("receive_question", "analyze_question")
        graph.add_edge("analyze_question", "build_source_selection_plan")
        graph.add_edge("build_source_selection_plan", "validate_plan")
        graph.add_conditional_edges(
            "validate_plan",
            self._route_after_validation,
            {
                "execute": "execute_selected_source",
                "reject": "reject_request",
            },
        )
        graph.add_edge("execute_selected_source", "return_answer")
        graph.add_edge("return_answer", "show_trace")
        graph.add_edge("reject_request", "show_trace")
        graph.add_edge("show_trace", END)
        return graph.compile()

    def _receive_question(self, state: WorkflowState) -> WorkflowState:
        return {
            **state,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.RECEIVE_QUESTION,
                label="Receive question",
                message="The workflow received the business question.",
            ),
        }

    def _analyze_question(self, state: WorkflowState) -> WorkflowState:
        analysis = self.analyzer.analyze(state["question"])
        return {
            **state,
            "analysis": analysis,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.ANALYZE_QUESTION,
                label="Analyze question",
                message=f"Detected intent candidate: {analysis.intent.value}.",
            ),
        }

    def _build_source_selection_plan(self, state: WorkflowState) -> WorkflowState:
        plan = self.planner.plan_from_analysis(state["analysis"])
        return {
            **state,
            "plan": plan,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.BUILD_SOURCE_SELECTION_PLAN,
                label="Build source-selection plan",
                message=plan.message,
                selected_sources=plan.selected_sources,
            ),
        }

    def _validate_plan(self, state: WorkflowState) -> WorkflowState:
        validation = self.validator.validate(state["plan"])
        return {
            **state,
            "validation": validation,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.VALIDATE_PLAN,
                label="Validate plan",
                message=validation.message,
                status=(
                    WorkflowStepStatus.COMPLETED
                    if validation.is_valid
                    else WorkflowStepStatus.FAILED
                ),
                selected_sources=state["plan"].selected_sources,
            ),
        }

    def _execute_selected_source(self, state: WorkflowState) -> WorkflowState:
        execution = self.executor.execute(state["plan"])
        return {
            **state,
            "execution": execution,
            "evidence": execution.evidence,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.EXECUTE_SELECTED_SOURCE,
                label="Execute selected source",
                message="Executed only the sources selected by the validated plan.",
                selected_sources=state["plan"].selected_sources,
            ),
        }

    def _return_answer(self, state: WorkflowState) -> WorkflowState:
        execution = state["execution"]
        return {
            **state,
            "answer": execution.answer,
            "status": WorkflowStatus.ANSWERED,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.RETURN_ANSWER,
                label="Return answer",
                message="Composed the answer from selected evidence.",
                selected_sources=state["plan"].selected_sources,
            ),
        }

    def _reject_request(self, state: WorkflowState) -> WorkflowState:
        validation = state["validation"]
        plan = state["plan"]
        status = self._workflow_status_for_rejection(plan.status)
        answer = validation.message
        trace = self._append_trace(
            state,
            step=WorkflowStepName.REJECT_REQUEST,
            label="Reject request safely",
            message="The workflow stopped before evidence execution.",
            status=WorkflowStepStatus.COMPLETED,
            selected_sources=plan.selected_sources,
        )
        trace = (
            *trace,
            WorkflowTraceStep(
                step=WorkflowStepName.EXECUTE_SELECTED_SOURCE,
                label="Execute selected source",
                status=WorkflowStepStatus.SKIPPED,
                message="Skipped because validation failed.",
                selected_sources=plan.selected_sources,
            ),
            WorkflowTraceStep(
                step=WorkflowStepName.RETURN_ANSWER,
                label="Return answer",
                status=WorkflowStepStatus.SKIPPED,
                message="Returned the safe rejection reason instead of an evidence answer.",
                selected_sources=(),
            ),
        )
        return {
            **state,
            "answer": answer,
            "status": status,
            "evidence": (),
            "trace": trace,
        }

    def _show_trace(self, state: WorkflowState) -> WorkflowState:
        return {
            **state,
            "trace": self._append_trace(
                state,
                step=WorkflowStepName.SHOW_TRACE,
                label="Show trace",
                message="Exposed the workflow trace for review.",
                selected_sources=state.get("plan").selected_sources if state.get("plan") else (),
            ),
        }

    def _route_after_validation(self, state: WorkflowState) -> str:
        return "execute" if state["validation"].is_valid else "reject"

    def _append_trace(
        self,
        state: WorkflowState,
        *,
        step: WorkflowStepName,
        label: str,
        message: str,
        status: WorkflowStepStatus = WorkflowStepStatus.COMPLETED,
        selected_sources=(),
    ) -> tuple[WorkflowTraceStep, ...]:
        return (
            *state.get("trace", ()),
            WorkflowTraceStep(
                step=step,
                label=label,
                status=status,
                message=message,
                selected_sources=tuple(selected_sources),
            ),
        )

    def _response_from_state(self, state: WorkflowState) -> WorkflowAnswerResponse:
        return WorkflowAnswerResponse(
            question=state["question"],
            status=state["status"],
            intent=state["plan"].intent,
            answer=state["answer"],
            plan=state["plan"],
            validation=state["validation"],
            evidence=state.get("evidence", ()),
            trace=state.get("trace", ()),
        )

    def _workflow_status_for_rejection(self, status: SelectionStatus) -> WorkflowStatus:
        if status == SelectionStatus.NEEDS_CLARIFICATION:
            return WorkflowStatus.NEEDS_CLARIFICATION
        if status == SelectionStatus.SERVICE_UNAVAILABLE:
            return WorkflowStatus.SERVICE_UNAVAILABLE
        return WorkflowStatus.REJECTED
