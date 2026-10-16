from __future__ import annotations

import copy
import logging
import os
import re
from typing import Any

from pydantic import ValidationError

from ..graph.config import load_local_env
from ..operational import TextToSqlMetrics
from ..structured_store import StructuredStore, open_structured_store
from .entity_resolver import EntityResolver
from .catalog import OBJECTS
from .llm_planner import (
    GeminiQueryPlanner,
    PlannerInvalidResponse,
    PlannerUnavailable,
    PlannerUnsupported,
)
from .llm_sql_guardrail import LlmSqlGuardrail, PreparedSqlCandidate
from .llm_sql_planner import GeminiSqlPlanner
from .models import (
    QueryFilter,
    QueryPlan,
    QueryStatus,
    QueryValidationResult,
    SemanticQueryResponse,
)
from .parser import AmbiguousEntityError, SemanticQueryParser, normalize_question
from .read_only_executor import ReadOnlySqliteExecutor as ReadOnlySqlExecutor
from .result_validator import QueryResultValidator
from .schema_context import SchemaContextSelector
from .sql_builder import SemanticSqlBuilder
from .sql_validator import SqlSafetyValidator
from .validator import QueryPlanValidator


DETERMINISTIC_CONFIDENCE_THRESHOLD = 0.85
LLM_FALLBACK_CONFIDENCE_THRESHOLD = 0.50
PLAN_CONFIDENCE_FLOOR = 0.85
logger = logging.getLogger(__name__)


class SemanticQueryService:
    def __init__(
        self,
        connection: Any | None = None,
        *,
        structured_store: StructuredStore | None = None,
        llm_fallback_enabled: bool | None = None,
        planner: GeminiQueryPlanner | None = None,
        sql_planner: GeminiSqlPlanner | None = None,
        text_to_sql_mode: str | None = None,
        text_to_sql_metrics: TextToSqlMetrics | None = None,
    ) -> None:
        load_local_env()
        self.connection = connection
        self.structured_store = structured_store or open_structured_store()
        self.parser = SemanticQueryParser(connection) if connection is not None else None
        self.entity_resolver = (
            EntityResolver(connection, self.parser) if connection is not None else None
        )
        self.schema_selector = SchemaContextSelector()
        self.validator = QueryPlanValidator()
        self.sql_builder = SemanticSqlBuilder()
        self.sql_validator = SqlSafetyValidator()
        self.result_validator = QueryResultValidator()
        self.executor = ReadOnlySqlExecutor(connection) if connection is not None else None
        self.llm_fallback_enabled = (
            self._env_enabled("SEMANTIC_LLM_FALLBACK_ENABLED")
            if llm_fallback_enabled is None
            else llm_fallback_enabled
        )
        self.planner = planner or GeminiQueryPlanner()
        self.text_to_sql_metrics = text_to_sql_metrics or TextToSqlMetrics(
            input_cost_per_million_usd=(
                self.structured_store.settings.llm_input_cost_per_million_usd
            ),
            output_cost_per_million_usd=(
                self.structured_store.settings.llm_output_cost_per_million_usd
            ),
        )
        self.sql_planner = sql_planner or GeminiSqlPlanner(
            usage_recorder=self.text_to_sql_metrics.record_usage
        )
        self.text_to_sql_mode = (
            self.structured_store.settings.text_to_sql_mode
            if text_to_sql_mode is None
            else text_to_sql_mode
        )
        if self.text_to_sql_mode not in {"off", "shadow", "active"}:
            raise ValueError("text_to_sql_mode must be off, shadow, or active")
        self.llm_sql_guardrail = LlmSqlGuardrail()

    def close(self) -> None:
        self.structured_store.close()

    def answer(
        self,
        question: str,
        *,
        scope_entities: tuple[tuple[str, str], ...] = (),
        limit: int | None = None,
    ) -> SemanticQueryResponse:
        if self.connection is not None:
            return self._answer_locked(question, scope_entities=scope_entities, limit=limit)

        with self.structured_store.connection() as connection:
            request_service = copy.copy(self)
            request_service.connection = connection
            request_service.parser = SemanticQueryParser(connection)
            request_service.entity_resolver = EntityResolver(connection, request_service.parser)
            request_service.executor = ReadOnlySqlExecutor(connection)
            return request_service._answer_locked(
                question,
                scope_entities=scope_entities,
                limit=limit,
            )

    def _answer_locked(
        self,
        question: str,
        *,
        scope_entities: tuple[tuple[str, str], ...] = (),
        limit: int | None = None,
    ) -> SemanticQueryResponse:
        try:
            plan = self.parser.parse(question)
        except AmbiguousEntityError as exc:
            choices = ", ".join(exc.values)
            return self._response(
                question,
                QueryStatus.NEEDS_CLARIFICATION,
                f"I found multiple matches for {exc.field}: {choices}. Please specify one.",
            )
        requested_limit = limit or self.structured_store.settings.sql_default_page_size
        if requested_limit > self.structured_store.settings.sql_max_page_size:
            return self._response(
                question,
                QueryStatus.REJECTED,
                "The requested page size exceeds the configured maximum.",
                validation=QueryValidationResult(
                    is_valid=False,
                    message="The requested page size is outside the configured bound.",
                    issues=("Use a smaller page size or request an aggregate.",),
                ),
            )
        plan = plan.model_copy(update={"limit": requested_limit}) if plan is not None else None
        if plan is not None and scope_entities:
            try:
                plan = self._apply_scope_entities(plan, scope_entities)
            except ValueError:
                return self._response(
                    question,
                    QueryStatus.REJECTED,
                    "A trusted workflow scope could not be applied safely.",
                )
        ranking_request = self._is_ranking_request(question)
        confidence = plan.confidence if plan is not None else 0.0
        if (
            plan is not None
            and plan.confidence >= DETERMINISTIC_CONFIDENCE_THRESHOLD
            and not ranking_request
        ):
            return self._execute_plan(question, plan)

        if confidence < LLM_FALLBACK_CONFIDENCE_THRESHOLD:
            return self._response(
                question,
                QueryStatus.NEEDS_CLARIFICATION,
                "I could not map the question confidently enough to the supported structured-data schema. Please clarify the requested data or filter.",
                plan=plan,
            )

        if confidence >= DETERMINISTIC_CONFIDENCE_THRESHOLD and ranking_request:
            confidence = LLM_FALLBACK_CONFIDENCE_THRESHOLD

        if not self.llm_fallback_enabled:
            return self._response(
                question,
                QueryStatus.NEEDS_CLARIFICATION,
                (
                    "I could not confidently map the requested ranking. Please clarify the measure or ranking direction."
                    if ranking_request and confidence >= LLM_FALLBACK_CONFIDENCE_THRESHOLD
                    else "I could not confidently map part of the question. Please clarify the requested data or filter."
                ),
                plan=plan,
            )

        schema = self.schema_selector.select(question, plan.object if plan else None)
        masked = self.entity_resolver.mask_question(question, allowed_fields=schema.fields)
        entity_placeholders = tuple(
            {"token": token, "fields": fields}
            for token, (fields, _value) in masked.values_by_placeholder.items()
        )
        repair_issues: tuple[str, ...] = ()
        for attempt in range(2):
            try:
                raw_plan = self.planner.plan(
                    masked_question=masked.question,
                    schema=schema,
                    entity_placeholders=entity_placeholders,
                    repair_issues=repair_issues,
                )
                raw_plan = self.entity_resolver.restore_plan_values(
                    raw_plan,
                    masked.values_by_placeholder,
                )
                candidate = self._parse_llm_plan(raw_plan, question)
                if candidate.object not in schema.objects:
                    raise ValueError("The planner selected an object outside the selected schema.")
                if scope_entities:
                    candidate = self._apply_scope_entities(candidate, scope_entities)
                self._validate_filter_values(candidate, question)
            except PlannerUnsupported as exc:
                return self._response(question, QueryStatus.UNSUPPORTED, str(exc))
            except PlannerInvalidResponse:
                repair_issues = ("The previous response was not a valid query plan JSON object.",)
                if attempt == 0:
                    continue
                return self._response(
                    question,
                    QueryStatus.REJECTED,
                    "The query could not be validated safely, so no data was retrieved.",
                    validation=QueryValidationResult(
                        is_valid=False,
                        message="The planner response was malformed.",
                        issues=repair_issues,
                    ),
                )
            except PlannerUnavailable as exc:
                return self._response(
                    question,
                    QueryStatus.UNAVAILABLE,
                    "The semantic planner is temporarily unavailable. Please try again later.",
                    plan=plan,
                )
            except (ValidationError, ValueError, TypeError) as exc:
                repair_issues = (self._safe_issue(exc),)
                if attempt == 0:
                    continue
                return self._response(
                    question,
                    QueryStatus.REJECTED,
                    "The query could not be validated safely, so no data was retrieved.",
                    plan=plan,
                    validation=QueryValidationResult(
                        is_valid=False,
                        message="The planner response did not satisfy the approved query-plan contract.",
                        issues=repair_issues,
                    ),
                )

            result = self._execute_plan(question, candidate)
            if result.status != QueryStatus.REJECTED:
                return result
            repair_issues = (
                "The previous plan failed a local allowlist or read-only query guardrail. Correct the plan using only the supplied catalog.",
            )
            if attempt == 1:
                return result

        return self._response(question, QueryStatus.REJECTED, "The query was rejected safely.")

    def _apply_scope_entities(
        self,
        plan: QueryPlan,
        scope_entities: tuple[tuple[str, str], ...],
    ) -> QueryPlan:
        fields_by_object = {
            "property": {
                "property_id": "properties.property_id",
                "project_id": "properties.project_id",
            },
            "invoice": {
                "invoice_id": "invoices.invoice_id",
                "project_id": "invoices.project_id",
                "property_id": "invoices.property_id",
                "vendor_id": "invoices.vendor_id",
                "po_id": "invoices.po_id",
                "cost_code": "invoices.cost_code",
            },
            "vendor": {"vendor_id": "vendors.vendor_id"},
            "budget": {
                "budget_id": "budgets.budget_id",
                "project_id": "budgets.project_id",
                "property_id": "budgets.property_id",
                "cost_code": "budgets.cost_code",
            },
        }
        field_map = fields_by_object[plan.object]
        filters = list(plan.filters)
        for entity_type, value in scope_entities:
            field = field_map.get(entity_type)
            if field is None:
                raise ValueError("The workflow entity is not valid for the selected object.")
            existing = tuple(item for item in filters if item.field == field)
            if existing and any(str(item.value).casefold() != value.casefold() for item in existing):
                raise ValueError("The query conflicts with its trusted workflow scope.")
            if not existing:
                filters.append(
                    QueryFilter(field=field, operator="=", value=value, confidence=1.0)
                )
        return plan.model_copy(update={"filters": tuple(filters)})

    def _execute_plan(self, question: str, plan: QueryPlan) -> SemanticQueryResponse:
        validation = self.validator.validate(plan)
        if not validation.is_valid:
            return self._response(
                question,
                QueryStatus.REJECTED,
                "The query could not be validated safely, so no data was retrieved.",
                plan=plan,
                validation=validation,
            )

        try:
            built = self.sql_builder.build(plan)
        except (KeyError, ValueError) as exc:
            return self._response(
                question,
                QueryStatus.REJECTED,
                "The query could not be generated from the approved plan.",
                plan=plan,
                validation=QueryValidationResult(
                    is_valid=False,
                    message="Local query generation rejected the plan.",
                    issues=(self._safe_issue(exc),),
                ),
            )

        sql_validation = self.sql_validator.validate(
            plan=plan,
            sql=built.sql,
            parameters=built.parameters,
        )
        if not sql_validation.is_valid:
            return self._response(
                question,
                QueryStatus.REJECTED,
                "The generated query did not pass the read-only safety checks.",
                plan=plan,
                validation=sql_validation,
                sql=built.sql,
                parameters=built.parameters,
            )

        candidate = self._prepare_llm_sql(question, plan, built)
        execution_query = (
            candidate.query
            if self.text_to_sql_mode == "active" and candidate is not None and candidate.query
            else built
        )
        if execution_query is not built:
            self.text_to_sql_metrics.record_event("active_executions")

        try:
            rows = self.executor.fetch_all(execution_query.sql, execution_query.parameters)
        except Exception as exc:
            if execution_query is not built:
                self.text_to_sql_metrics.record_event("semantic_retries")
                repaired = self._prepare_llm_sql(
                    question,
                    plan,
                    built,
                    repair_issue="The previous SQL did not compile against the approved schema.",
                )
                if repaired is not None and repaired.query is not None:
                    try:
                        rows = self.executor.fetch_all(repaired.query.sql, repaired.query.parameters)
                        execution_query = repaired.query
                    except Exception:
                        logger.warning("Repaired LLM SQL failed; using deterministic fallback.")
                        self.text_to_sql_metrics.record_event("fallback_executions")
                        fallback_rows = self._execute_fallback(built)
                        if fallback_rows is None:
                            return self._database_unavailable_response(question, plan, validation)
                        rows = fallback_rows
                        execution_query = built
                else:
                    self.text_to_sql_metrics.record_event("fallback_executions")
                    fallback_rows = self._execute_fallback(built)
                    if fallback_rows is None:
                        return self._database_unavailable_response(question, plan, validation)
                    rows = fallback_rows
                    execution_query = built
            else:
                logger.exception("Structured query execution failed", exc_info=exc)
                return self._response(
                    question,
                    QueryStatus.UNAVAILABLE,
                    "The structured data store could not complete the request.",
                    plan=plan,
                    validation=validation,
                )

        if self.text_to_sql_mode == "shadow" and candidate is not None and candidate.query:
            self._compare_shadow_result(question, plan, candidate, rows)

        result_validation = self.result_validator.validate(plan, rows)
        if not result_validation.is_valid:
            return self._response(
                question,
                QueryStatus.REJECTED,
                "The database result did not pass validation, so it was not returned.",
                plan=plan,
                validation=result_validation,
            )

        if plan.limit == 1 and plan.sort and rows:
            tied_rows = self._top_tie_rows(plan)
            if tied_rows is None:
                return self._response(
                    question,
                    QueryStatus.REJECTED,
                    "The top result could not be checked for a tie, so no unique result was returned.",
                    plan=plan,
                    validation=QueryValidationResult(
                        is_valid=False,
                        message="Top-result tie check failed.",
                        issues=("The bounded tie-check query failed validation or execution.",),
                    ),
                )
            if tied_rows:
                return self._response(
                    question,
                    QueryStatus.NEEDS_CLARIFICATION,
                    "The top result is tied across multiple records, so there is no unique top match.",
                    plan=plan,
                    validation=validation,
                    evidence=self._evidence_references(tied_rows),
                )

        status = QueryStatus.OK if rows else QueryStatus.EMPTY
        return self._response(
            question,
            status,
            self._format_answer(plan, rows),
            plan=plan,
            validation=validation,
            rows=rows,
            evidence=self._evidence_references(rows),
            sql=execution_query.sql,
            parameters=execution_query.parameters,
        )

    def _prepare_llm_sql(
        self,
        question: str,
        plan: QueryPlan,
        baseline,
        *,
        repair_issue: str | None = None,
    ) -> PreparedSqlCandidate | None:
        if self.text_to_sql_mode == "off":
            return None
        self.text_to_sql_metrics.record_event("candidate_preparations")
        schema = self.schema_selector.select(question, plan.object)
        try:
            masked_question, placeholder_contract = self._sql_prompt_contract(
                question, plan, baseline.parameters, schema.fields
            )
            approved_joins = tuple(
                line.strip()
                for line in baseline.sql.splitlines()
                if "JOIN " in line.upper()
            )
            intent_contract = {
                    "object": plan.object,
                    "base_from": (
                        f"{OBJECTS[plan.object].table} {OBJECTS[plan.object].alias}"
                    ),
                    "return_fields": tuple(
                        {
                            "field": field,
                            "sql_expression": self.sql_builder._field_sql(
                                field, OBJECTS[plan.object].alias
                            ),
                            "result_alias": self.sql_builder._column_alias(
                                field, plan.object
                            ),
                        }
                        for field in plan.return_fields
                    ),
                    "group_by": plan.group_by,
                    "aggregations": tuple(
                        {
                            "function": item.function,
                            "field": item.field,
                            "alias": item.alias,
                            "sql_expression": self.sql_builder._aggregation_sql(item),
                        }
                        for item in plan.aggregations
                    ),
                    "conditions": tuple(item.metric for item in plan.conditions),
                    "sort": tuple(
                        {
                            "field": item.field,
                            "direction": item.direction,
                            "sql_expression": self.sql_builder._field_sql(
                                item.field, OBJECTS[plan.object].alias
                            ),
                        }
                        for item in plan.sort
                    ),
                    "required_select_sql": self.sql_builder._select_clause(
                        plan, OBJECTS[plan.object].alias
                    ),
                    "required_where_sql": self._required_clause(
                        baseline.sql, "WHERE", ("GROUP BY", "ORDER BY", "LIMIT")
                    ),
                    "required_group_by_sql": self._required_clause(
                        baseline.sql, "GROUP BY", ("ORDER BY", "LIMIT")
                    ),
                    "required_order_by_sql": self._required_clause(
                        baseline.sql, "ORDER BY", ("LIMIT",)
                    ),
                }
            proposal = None
            invalid_response_repair = repair_issue
            for attempt in range(2):
                try:
                    self.text_to_sql_metrics.record_event("proposal_requests")
                    proposal = self.sql_planner.propose(
                        masked_question=masked_question,
                        schema=schema,
                        placeholder_contract=placeholder_contract,
                        intent_contract=intent_contract,
                        approved_joins=approved_joins,
                        repair_issue=invalid_response_repair,
                    )
                    self.text_to_sql_metrics.record_event("proposals_returned")
                    break
                except PlannerInvalidResponse:
                    self.text_to_sql_metrics.record_event("invalid_responses")
                    if attempt == 1 or repair_issue is not None:
                        raise
                    invalid_response_repair = "The previous response was not one valid SQL JSON object."
            if proposal is None:
                raise PlannerInvalidResponse("The SQL planner did not return a proposal.")
        except (PlannerUnavailable, PlannerInvalidResponse, ValueError) as exc:
            self.text_to_sql_metrics.record_event("planner_failures")
            if isinstance(exc, PlannerUnavailable):
                self.text_to_sql_metrics.record_event(
                    f"planner_failure_{exc.category}"
                )
            self.text_to_sql_metrics.record_event("fallback_selections")
            logger.warning("LLM SQL proposal unavailable; using deterministic fallback: %s", type(exc).__name__)
            return None

        prepared = self.llm_sql_guardrail.prepare(
            plan=plan,
            proposed_sql=proposal,
            baseline=baseline,
        )
        if not prepared.validation.is_valid or prepared.query is None:
            self.text_to_sql_metrics.record_event("security_rejections")
            self.text_to_sql_metrics.record_event("fallback_selections")
            logger.warning(
                "LLM SQL rejected; using deterministic fallback: %s",
                "; ".join(prepared.validation.issues),
            )
            return prepared
        try:
            cost_validation = self.executor.validate_cost(
                prepared.query.sql,
                prepared.query.parameters,
                max_cost=self.structured_store.settings.text_to_sql_max_plan_cost,
                max_rows=self.structured_store.settings.text_to_sql_max_estimated_rows,
            )
        except Exception:
            self.text_to_sql_metrics.record_event("cost_check_failures")
            self.text_to_sql_metrics.record_event("fallback_selections")
            logger.warning("LLM SQL EXPLAIN failed; using deterministic fallback.")
            return None
        if not cost_validation.is_valid:
            self.text_to_sql_metrics.record_event("cost_rejections")
            self.text_to_sql_metrics.record_event("fallback_selections")
            logger.warning("LLM SQL exceeded cost limits; using deterministic fallback.")
            return PreparedSqlCandidate(query=None, validation=cost_validation)
        self.text_to_sql_metrics.record_event("accepted_candidates")
        return prepared

    def _required_clause(
        self,
        sql: str,
        clause: str,
        following_clauses: tuple[str, ...],
    ) -> str:
        end = "|".join(rf"\n{re.escape(item)}\b" for item in following_clauses)
        match = re.search(
            rf"\n{re.escape(clause)}\s+(.*?)(?={end}|$)",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""

    def _sql_prompt_contract(
        self,
        question: str,
        plan: QueryPlan,
        parameters: dict[str, Any],
        allowed_fields: tuple[str, ...],
    ) -> tuple[str, tuple[dict[str, Any], ...]]:
        masked = self.entity_resolver.mask_question(question, allowed_fields=allowed_fields)
        masked_question = masked.question
        contracts: list[dict[str, Any]] = []
        filter_by_name = {
            f"filter_{index}": item for index, item in enumerate(plan.filters, start=1)
        }
        condition_by_name = {
            f"condition_{index}": item for index, item in enumerate(plan.conditions, start=1)
        }
        for name, value in parameters.items():
            if name == "limit":
                continue
            item = filter_by_name.get(name) or condition_by_name.get(name)
            if item is None:
                raise ValueError("A query parameter has no validated intent contract.")
            prompt_token = f"<{name.upper()}>"
            replaced = False
            for token, (_fields, actual_value) in masked.values_by_placeholder.items():
                if str(actual_value).casefold() == str(value).casefold() and token in masked_question:
                    masked_question = masked_question.replace(token, prompt_token, 1)
                    replaced = True
                    break
            if not replaced:
                value_text = normalize_question(str(value))
                pattern = rf"(?<![a-z0-9]){re.escape(value_text)}(?![a-z0-9])"
                masked_question, count = re.subn(pattern, prompt_token, masked_question, count=1)
                replaced = bool(count)
            contracts.append(
                {
                    "question_token": prompt_token if replaced else "trusted_scope_not_in_question",
                    "placeholder": f":{name}",
                    "field_or_metric": getattr(item, "field", getattr(item, "metric", "")),
                    "operator": item.operator,
                    "type": type(value).__name__,
                }
            )
        leak_check_question = re.sub(r"<[A-Z0-9_]+>", "", masked_question)
        for name, value in parameters.items():
            if name == "limit" or not isinstance(value, (str, int, float)):
                continue
            if normalize_question(str(value)) in normalize_question(leak_check_question):
                raise ValueError("A backend-resolved value remained in the masked question.")
        return masked_question, tuple(contracts)

    def _execute_fallback(self, built) -> tuple[dict[str, Any], ...] | None:
        try:
            return self.executor.fetch_all(built.sql, built.parameters)
        except Exception as exc:
            logger.exception("Deterministic structured-query fallback failed", exc_info=exc)
            return None

    def _database_unavailable_response(
        self,
        question: str,
        plan: QueryPlan,
        validation: QueryValidationResult,
    ) -> SemanticQueryResponse:
        return self._response(
            question,
            QueryStatus.UNAVAILABLE,
            "The structured data store could not complete the request.",
            plan=plan,
            validation=validation,
        )

    def _compare_shadow_result(
        self,
        question: str,
        plan: QueryPlan,
        candidate: PreparedSqlCandidate,
        baseline_rows: tuple[dict[str, Any], ...],
    ) -> None:
        try:
            candidate_rows = self.executor.fetch_all(
                candidate.query.sql,
                candidate.query.parameters,
            )
            matches = candidate_rows == baseline_rows
            self.text_to_sql_metrics.record_event(
                "shadow_matches" if matches else "shadow_mismatches"
            )
            logger.info(
                "text_to_sql_shadow comparison match=%s object=%s baseline_rows=%d candidate_rows=%d",
                matches,
                plan.object,
                len(baseline_rows),
                len(candidate_rows),
            )
        except Exception:
            self.text_to_sql_metrics.record_event("shadow_execution_failures")
            logger.warning("text_to_sql_shadow candidate execution failed for validated query")

    def _parse_llm_plan(self, raw_plan: dict[str, Any], question: str) -> QueryPlan:
        allowed_keys = {
            "object", "filters", "conditions", "aggregations", "group_by",
            "return_fields", "sort", "limit",
        }
        if set(raw_plan) - allowed_keys:
            raise ValueError("The planner returned fields outside the query-plan contract.")
        plan_data = dict(raw_plan)
        for collection in ("filters", "conditions", "aggregations", "group_by", "sort"):
            plan_data.setdefault(collection, [])
        plan_data["confidence"] = PLAN_CONFIDENCE_FLOOR
        plan_data["normalized_question"] = normalize_question(question)
        plan_data["unresolved_terms"] = ()
        for collection in ("filters", "conditions", "aggregations"):
            entries = plan_data.get(collection, ())
            if not isinstance(entries, list):
                raise ValueError(f"Planner {collection} must be an array.")
            with_confidence: list[dict[str, Any]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError(f"Planner {collection} entries must be objects.")
                item = dict(entry)
                item["confidence"] = PLAN_CONFIDENCE_FLOOR
                with_confidence.append(item)
            plan_data[collection] = with_confidence
        return QueryPlan.model_validate(plan_data)

    def _validate_filter_values(self, plan: QueryPlan, question: str) -> None:
        normalized_question = normalize_question(question)
        for item in plan.filters:
            normalized_value = normalize_question(str(item.value))
            if not normalized_value or not re.search(
                rf"\b{re.escape(normalized_value)}\b", normalized_question
            ):
                raise ValueError("A filter value was not stated or resolved from the question.")

    def _top_tie_rows(self, plan: QueryPlan) -> tuple[dict[str, Any], ...] | None:
        probe_plan = plan.model_copy(update={"limit": 2})
        probe = self.sql_builder.build(probe_plan)
        safety = self.sql_validator.validate(
            plan=probe_plan,
            sql=probe.sql,
            parameters=probe.parameters,
        )
        if not safety.is_valid:
            return None
        try:
            rows = self.executor.fetch_all(probe.sql, probe.parameters)
        except Exception as exc:
            logger.exception("Structured tie-check execution failed", exc_info=exc)
            return None
        if not self.result_validator.validate(probe_plan, rows).is_valid or len(rows) < 2:
            return ()
        sort_alias = self._result_alias(plan.sort[0].field, plan.object)
        if sort_alias not in rows[0] or sort_alias not in rows[1]:
            return None
        return rows[:2] if rows[0][sort_alias] == rows[1][sort_alias] else ()

    def _result_alias(self, field: str, object_name: str) -> str:
        if object_name in {"property", "vendor"}:
            return field.split(".", 1)[1]
        return {
            "properties.property_name": "property_name",
            "properties.city": "property_city",
            "properties.property_type": "property_type",
            "properties.status": "property_status",
            "vendors.vendor_name": "vendor_name",
            "vendors.category": "vendor_category",
            "vendors.city": "vendor_city",
            "vendors.tax_id": "vendor_tax_id",
        }.get(field, field.split(".", 1)[1])

    def _is_ranking_request(self, question: str) -> bool:
        normalized = normalize_question(question)
        return any(
            re.search(rf"\b{term}\b", normalized)
            for term in (
                "top", "highest", "lowest", "most", "least", "largest", "smallest", "best", "worst", "rank"
            )
        )

    def _format_answer(self, plan: QueryPlan, rows: tuple[dict[str, Any], ...]) -> str:
        if not rows:
            return f"No matching {plan.object} records were found."

        if plan.aggregations:
            row_parts: list[str] = []
            for row in rows:
                grouped = tuple(
                    str(row.get(self._result_alias(field, plan.object), row.get(field.split(".", 1)[1], "")))
                    for field in plan.group_by
                )
                values = tuple(
                    f"{aggregation.alias} is {row.get(aggregation.alias)}"
                    for aggregation in plan.aggregations
                )
                label = ", ".join(grouped) if grouped else "overall"
                row_parts.append(f"{label}: {', '.join(values)}")
            return f"Aggregate result: {'; '.join(row_parts)}."

        label_field = {
            "property": "property_name",
            "invoice": "invoice_id",
            "vendor": "vendor_name",
            "budget": "cost_code",
            "payment": "payment_id",
            "purchase_order": "po_id",
        }[plan.object]
        labels = tuple(str(row.get(label_field, "")) for row in rows)
        if len(labels) == 1:
            return f"Found 1 matching {plan.object}: {labels[0]}."
        return f"Found {len(labels)} matching {plan.object} records: {', '.join(labels)}."

    def _evidence_references(self, rows: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
        identifiers = ("invoice_id", "property_id", "vendor_id", "budget_id", "project_id", "po_id")
        references = []
        for index, row in enumerate(rows, start=1):
            matched = tuple(f"{key}={row[key]}" for key in identifiers if row.get(key) is not None)
            references.append(", ".join(matched) if matched else f"result row {index}")
        return tuple(references)

    def _response(
        self,
        question: str,
        status: QueryStatus,
        answer: str,
        *,
        plan: QueryPlan | None = None,
        validation: QueryValidationResult | None = None,
        rows: tuple[dict[str, Any], ...] = (),
        evidence: tuple[str, ...] = (),
        sql: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> SemanticQueryResponse:
        return SemanticQueryResponse(
            question=question,
            status=status,
            answer=answer,
            plan=plan,
            validation=validation,
            rows=rows,
            evidence=evidence,
            sql=sql,
            parameters=parameters or {},
        )

    def _safe_issue(self, error: Exception) -> str:
        if isinstance(error, ValidationError):
            return "The returned object did not match the required query-plan structure."
        if isinstance(error, TypeError):
            return "The returned query plan had an invalid data type."
        return "The returned query plan violated the selected schema or entity constraints."

    def _env_enabled(self, name: str) -> bool:
        return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}
