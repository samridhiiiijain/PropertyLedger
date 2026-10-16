from __future__ import annotations

from decimal import Decimal
from contextlib import asynccontextmanager
import logging
from time import perf_counter
from typing import Any, Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .application_services import ApplicationServices, build_application_services
from .documents.document_repository import DocumentProcessingTimeout
from .graph.repository import GraphUnavailableError, Neo4jGraphRepository
from .models import (
    BusinessDefinition,
    BusinessDefinitionListResponse,
    DocumentAnswerResponse,
    HealthResponse,
    LinkedDocumentEvidence,
    LinkedInvoiceEvidenceResponse,
    LinkedInvoiceFacts,
    RelationshipPathResponse,
)
from .selection.selection_models import EvidenceSelectionPlan
from .semantic_query.models import SemanticQueryPublicResponse, SemanticQueryRequest
from .workflow.workflow_models import WorkflowAnswerResponse
from .operational import (
    readiness_payload,
    request_id_context,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    services = build_application_services()
    application.state.services = services
    try:
        yield
    finally:
        services.close()
        del application.state.services


app = FastAPI(
    title="PropertyLedger API",
    version="1.0.0",
    lifespan=lifespan,
)


def application_services(request: Request) -> ApplicationServices:
    return request.app.state.services


Services = Annotated[ApplicationServices, Depends(application_services)]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type"],
)


@app.middleware("http")
async def operational_middleware(request: Request, call_next):
    services: ApplicationServices = request.app.state.services
    request_id = str(uuid4())
    token = request_id_context.set(request_id)
    started_at = perf_counter()
    status_code = 500
    services.request_metrics.begin(request.url.path)
    try:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > services.settings.max_request_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                status_code = 413
                response = JSONResponse(
                    status_code=status_code,
                    content={"detail": "Request body exceeds the configured size limit."},
                )
                response.headers["X-Request-ID"] = request_id
                return response

        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_ms = (perf_counter() - started_at) * 1000
        services.request_metrics.record(request.url.path, status_code, duration_ms)
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%d duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            status_code,
            duration_ms,
        )
        request_id_context.reset(token)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version="1.0.0")


@app.get("/ready")
def readiness(services: Services) -> JSONResponse:
    payload, ready = readiness_payload(
        structured_store=services.semantic_query_service.structured_store,
        document_repository=services.document_repository,
        graph_repository_factory=Neo4jGraphRepository,
    )
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@app.get("/metrics")
def metrics(services: Services) -> dict[str, object]:
    return {
        "requests": services.request_metrics.snapshot(),
        "structured_store_pool": services.semantic_query_service.structured_store.pool_metrics(),
        "text_to_sql": services.semantic_query_service.text_to_sql_metrics.snapshot(),
    }


@app.get("/api/invoices")
def list_invoices(
    services: Services,
    project_id: Annotated[
        str | None,
        Query(
            min_length=5,
            max_length=5,
            pattern=r"^PR\d{3}$",
            description="Optional stable project identifier, for example PR204.",
        ),
    ] = None,
) -> dict:
    question = "show invoices" if project_id is None else f"show invoices for {project_id}"
    response = services.semantic_query_service.answer(question)
    payment_question = (
        "show payments" if project_id is None else f"show payments for {project_id}"
    )
    payment_response = services.semantic_query_service.answer(payment_question)
    payments_by_invoice: dict[str, list[dict[str, str]]] = {}
    if payment_response.is_successful:
        for payment in payment_response.rows:
            payments_by_invoice.setdefault(str(payment["invoice_id"]), []).append(
                {
                    "payment_id": str(payment["payment_id"]),
                    "amount": _money_text(payment["amount"]),
                    "payment_date": str(payment["payment_date"]),
                }
            )
    return {
        "items": [
            _invoice_response_item(row, payments_by_invoice.get(str(row["invoice_id"]), []))
            for row in response.rows
        ],
        "count": len(response.rows),
        "filters": {"project_id": project_id},
    }


ProjectPath = Annotated[
    str,
    Path(
        min_length=5,
        max_length=5,
        pattern=r"^PR\d{3}$",
        description="Stable project identifier, for example PR204.",
    ),
]


def _money_text(value: object) -> str:
    return f"{float(value):.2f}"


def _invoice_response_item(row: dict, payments: list[dict[str, str]]) -> dict:
    return {
        "invoice_id": row["invoice_id"],
        "invoice_number": row["invoice_id"],
        "property": {
            "property_id": row["property_id"],
            "name": row["property_name"],
            "city": row["property_city"],
            "property_type": row["property_type"],
            "status": row["property_status"],
        },
        "project": {"project_id": row["project_id"], "name": row["project_id"]},
        "vendor": {
            "vendor_id": row["vendor_id"],
            "name": row["vendor_name"],
            "category": row["vendor_category"],
            "city": row["vendor_city"],
            "tax_id": row["vendor_tax_id"],
        },
        "purchase_order": {
            "po_id": row["po_id"],
            "committed_amount": _money_text(row["po_total"]),
            "currency": "INR",
        },
        "budget": {
            "budget_id": row.get("budget_id"),
            "cost_code": row["cost_code"],
            "approved_amount": (
                _money_text(row["budget_amount"])
                if row.get("budget_amount") is not None
                else None
            ),
            "currency": "INR",
        },
        "payments": payments,
        "invoice_date": row["invoice_date"],
        "due_date": row["due_date"],
        "amount": _money_text(row["invoice_amount"]),
        "paid_amount": _money_text(row["paid_amount"]),
        "outstanding_amount": _money_text(row["outstanding_amount"]),
        "currency": "INR",
        "status": str(row["status"]).strip().upper().replace(" ", "_"),
    }


def _unpaid_invoice_item(row: dict) -> dict:
    return {
        "invoice_id": row["invoice_id"],
        "vendor_id": row["vendor_id"],
        "vendor_name": row["vendor_name"],
        "status": str(row["status"]).strip().upper().replace(" ", "_"),
        "invoice_amount": _money_text(row["invoice_amount"]),
        "paid_amount": _money_text(row["paid_amount"]),
        "outstanding_amount": _money_text(row["outstanding_amount"]),
        "due_date": row["due_date"],
    }


def _po_variance_item(row: dict) -> dict:
    return {
        "invoice_id": row["invoice_id"],
        "po_id": row["po_id"],
        "vendor_name": row["vendor_name"],
        "invoice_amount": _money_text(row["invoice_amount"]),
        "po_total": _money_text(row["po_total"]),
        "variance_amount": _money_text(row["po_variance_amount"]),
        "cost_code": row["cost_code"],
    }


def _budget_variance_item(row: dict) -> dict:
    return {
        "budget_id": row["budget_id"],
        "cost_code": row["cost_code"],
        "cost_category": "",
        "budget_amount": _money_text(row["budget_amount"]),
        "committed_amount": _money_text(row["committed_amount"]),
        "variance_amount": _money_text(row["budget_variance_amount"]),
    }


@app.get(
    "/api/projects/{project_id}/unpaid-invoices",
)
def unpaid_invoices(services: Services, project_id: ProjectPath) -> dict:
    response = services.semantic_query_service.answer(f"show unpaid invoices for {project_id}")
    return {
        "project_id": project_id,
        "items": [_unpaid_invoice_item(row) for row in response.rows],
        "count": len(response.rows),
    }


@app.get(
    "/api/projects/{project_id}/po-variances",
)
def purchase_order_variances(services: Services, project_id: ProjectPath) -> dict:
    response = services.semantic_query_service.answer(f"show PO variance invoices for {project_id}")
    return {
        "project_id": project_id,
        "items": [_po_variance_item(row) for row in response.rows],
        "count": len(response.rows),
    }


@app.get(
    "/api/projects/{project_id}/budget-variances",
)
def budget_variances(services: Services, project_id: ProjectPath) -> dict:
    response = services.semantic_query_service.answer(f"show cost codes over budget for {project_id}")
    return {
        "project_id": project_id,
        "items": [_budget_variance_item(row) for row in response.rows],
        "count": len(response.rows),
    }


@app.get("/api/business-definitions", response_model=BusinessDefinitionListResponse)
def list_business_definitions(services: Services) -> BusinessDefinitionListResponse:
    definitions = tuple(
        BusinessDefinition(**definition.__dict__)
        for definition in services.business_definition_service.list_definitions()
    )
    return BusinessDefinitionListResponse(items=definitions, count=len(definitions))


TermSlugPath = Annotated[
    str,
    Path(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9-]+$",
        description="Approved business term slug, for example po-variance.",
    ),
]


@app.get("/api/business-definitions/{term_slug}", response_model=BusinessDefinition)
def get_business_definition(services: Services, term_slug: TermSlugPath) -> BusinessDefinition:
    definition = services.business_definition_service.get_definition(term_slug)
    if definition is None:
        raise HTTPException(
            status_code=404,
            detail=f"No approved business definition was found for '{term_slug}'.",
        )

    return BusinessDefinition(**definition.__dict__)


@app.get("/api/evidence-selection", response_model=EvidenceSelectionPlan)
def select_evidence(
    services: Services,
    question: Annotated[
        str,
        Query(
            min_length=8,
            max_length=300,
            description=(
                "Business question to classify before execution. The response identifies "
                "the minimum evidence sources required to answer safely."
            ),
        ),
    ],
) -> EvidenceSelectionPlan:
    return services.evidence_planner.plan(question)


@app.get("/api/semantic-query", response_model=SemanticQueryPublicResponse)
def semantic_query(
    services: Services,
    question: Annotated[
        str,
        Query(
            min_length=4,
            max_length=300,
            description="Natural-language question about approved structured business data. Internal query plans and SQL are not returned.",
        ),
    ],
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=1000,
            description="Optional detail page size. Aggregates still calculate over all matching records.",
        ),
    ] = None,
) -> SemanticQueryPublicResponse:
    return _semantic_query_response(services, question, limit)


@app.post("/api/semantic-query", response_model=SemanticQueryPublicResponse)
def semantic_query_post(
    services: Services,
    request: SemanticQueryRequest,
) -> SemanticQueryPublicResponse:
    return _semantic_query_response(services, request.question, request.limit)


def _semantic_query_response(
    services: ApplicationServices,
    question: str,
    limit: int | None,
) -> SemanticQueryPublicResponse:
    result = services.semantic_query_service.answer(question, limit=limit)
    return SemanticQueryPublicResponse(
        question=result.question,
        status=result.status,
        answer=result.answer,
        rows=tuple(_json_safe_row(row) for row in result.rows),
        evidence=result.evidence,
    )


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Expose database decimals as JSON numbers while preserving whole amounts."""
    return {key: _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@app.get("/api/workflow-answer", response_model=WorkflowAnswerResponse)
def workflow_answer(
    services: Services,
    question: Annotated[
        str,
        Query(
            min_length=8,
            max_length=300,
            description=(
                "Business question to run through the validated Day 8 workflow. "
                "The response includes the source-selection plan, validation, evidence, "
                "answer, and trace."
            ),
        ),
    ],
) -> WorkflowAnswerResponse:
    try:
        return services.workflow.run(question)
    except DocumentProcessingTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/document-answer", response_model=DocumentAnswerResponse)
def document_answer(
    services: Services,
    question: Annotated[
        str,
        Query(
            min_length=8,
            max_length=300,
            description="Document evidence question to answer from the local document corpus.",
        ),
    ],
    project_id: Annotated[
        str | None,
        Query(
            min_length=5,
            max_length=5,
            pattern=r"^PR\d{3}$",
            description="Optional project identifier used to keep evidence scoped.",
        ),
    ] = None,
) -> DocumentAnswerResponse:
    try:
        return services.document_repository.answer_question(
            question=question,
            project_id=project_id,
        )
    except DocumentProcessingTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


InvoicePath = Annotated[
    str,
    Path(
        min_length=7,
        max_length=7,
        pattern=r"^INV\d{4}$",
        description="Stable invoice identifier, for example INV5004.",
    ),
]


@app.get(
    "/api/invoices/{invoice_id}/linked-evidence",
    response_model=LinkedInvoiceEvidenceResponse,
)
def linked_invoice_evidence(
    services: Services,
    invoice_id: InvoicePath,
) -> LinkedInvoiceEvidenceResponse:
    try:
        result = services.linked_evidence_service.invoice_evidence(invoice_id)
    except DocumentProcessingTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    if result.invoice is None or result.facts is None:
        raise HTTPException(status_code=404, detail=result.answer)

    return LinkedInvoiceEvidenceResponse(
        invoice_id=result.facts.invoice_id,
        status=result.status,
        answer=result.answer,
        structured_facts=LinkedInvoiceFacts(
            invoice_id=result.facts.invoice_id,
            property_id=result.facts.property_id,
            project_id=result.facts.project_id,
            vendor_id=result.facts.vendor_id,
            po_id=result.facts.po_id,
            cost_code=result.facts.cost_code,
            status=result.facts.status,
            invoice_amount=result.facts.invoice_amount,
            po_amount=result.facts.po_amount,
            po_variance_amount=result.facts.po_variance_amount,
            paid_amount=result.facts.paid_amount,
            outstanding_amount=result.facts.outstanding_amount,
            currency=result.facts.currency,
        ),
        sources=tuple(
            LinkedDocumentEvidence(
                chunk_id=match.chunk.chunk_id,
                score=match.score,
                text=match.chunk.text,
                metadata=match.chunk.metadata,
                link_type=match.link_type,
                matched_identifiers=match.matched_identifiers,
            )
            for match in result.matches
        ),
    )


PropertyPath = Annotated[
    str,
    Path(
        min_length=4,
        max_length=4,
        pattern=r"^P\d{3}$",
        description="Stable property identifier, for example P204.",
    ),
]


@app.get(
    "/api/properties/{property_id}/po-variance-paths",
    response_model=RelationshipPathResponse,
)
def po_variance_relationship_paths(
    services: Services,
    property_id: PropertyPath,
) -> RelationshipPathResponse:
    try:
        return services.graph_service.trace_po_variance_paths(property_id)
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
