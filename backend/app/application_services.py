from __future__ import annotations

from dataclasses import dataclass

from .documents.document_repository import DocumentRepository
from .evidence.linked_evidence_service import LinkedEvidenceService
from .graph.repository import Neo4jGraphRepository
from .graph.service import GraphTraversalService
from .operational import RequestMetrics
from .runtime_config import RuntimeSettings, load_runtime_settings
from .selection.evidence_planner import EvidencePlanner
from .semantic_query.service import SemanticQueryService
from .semantics.service import BusinessDefinitionService
from .structured_store import StructuredStore
from .workflow.langgraph_workflow import LangGraphWorkflow
from .workflow.source_executor import WorkflowSourceExecutor


@dataclass
class ApplicationServices:
    settings: RuntimeSettings
    document_repository: DocumentRepository
    business_definition_service: BusinessDefinitionService
    semantic_query_service: SemanticQueryService
    linked_evidence_service: LinkedEvidenceService
    graph_service: GraphTraversalService
    evidence_planner: EvidencePlanner
    workflow: LangGraphWorkflow
    request_metrics: RequestMetrics

    def close(self) -> None:
        self.document_repository.close()
        self.graph_service.close()
        self.semantic_query_service.close()


def build_application_services(
    settings: RuntimeSettings | None = None,
) -> ApplicationServices:
    runtime_settings = settings or load_runtime_settings()
    structured_store = StructuredStore(runtime_settings)
    semantic_query_service = SemanticQueryService(structured_store=structured_store)
    document_repository = DocumentRepository(settings=runtime_settings)
    graph_service = GraphTraversalService(
        graph_repository=Neo4jGraphRepository(),
        semantic_query_service=semantic_query_service,
    )
    linked_evidence_service = LinkedEvidenceService(
        document_repository=document_repository,
        semantic_query_service=semantic_query_service,
    )
    evidence_planner = EvidencePlanner()
    workflow_source_executor = WorkflowSourceExecutor(
        document_repository=document_repository,
        linked_evidence_service=linked_evidence_service,
        graph_service=graph_service,
        semantic_query_service=semantic_query_service,
    )
    return ApplicationServices(
        settings=runtime_settings,
        document_repository=document_repository,
        business_definition_service=BusinessDefinitionService(),
        semantic_query_service=semantic_query_service,
        linked_evidence_service=linked_evidence_service,
        graph_service=graph_service,
        evidence_planner=evidence_planner,
        workflow=LangGraphWorkflow(
            planner=evidence_planner,
            executor=workflow_source_executor,
        ),
        request_metrics=RequestMetrics(),
    )
