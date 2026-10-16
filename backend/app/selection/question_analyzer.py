from __future__ import annotations

import re

from ..semantics.definitions import BUSINESS_DEFINITIONS, BusinessTermDefinition
from .selection_models import (
    AnalyzedQuestion,
    ApprovedTermReference,
    DetectedEntity,
    EntityType,
    QuestionIntent,
    QuestionSignal,
)


ENTITY_PATTERNS: tuple[tuple[EntityType, re.Pattern[str]], ...] = (
    (EntityType.PROJECT_ID, re.compile(r"\bPR\d{3}\b", re.IGNORECASE)),
    (EntityType.PROPERTY_ID, re.compile(r"\bP\d{3}\b", re.IGNORECASE)),
    (EntityType.INVOICE_ID, re.compile(r"\bINV\d{4}\b", re.IGNORECASE)),
    (EntityType.PO_ID, re.compile(r"\bPO\d{4}\b", re.IGNORECASE)),
    (EntityType.VENDOR_ID, re.compile(r"\bV\d{3}\b", re.IGNORECASE)),
    (EntityType.COST_CODE, re.compile(r"\bCC\d{3}\b", re.IGNORECASE)),
    (EntityType.DOCUMENT_ID, re.compile(r"\bDOC-[A-Z0-9-]+\b", re.IGNORECASE)),
)

DOCUMENT_SIGNALS = (
    "doc",
    "document",
    "documents",
    "procedure",
    "policy",
    "contract",
    "approval",
    "email",
    "checklist",
    "reconciliation",
    "note",
    "requires",
    "require",
    "say",
    "says",
)

RELATIONSHIP_SIGNALS = (
    "trace",
    "path",
    "paths",
    "relationship",
    "relationships",
    "connected",
    "connect",
    "graph",
    "multi hop",
    "multi-hop",
)

LINKED_EVIDENCE_SIGNALS = (
    "evidence",
    "explain",
    "missing",
    "support",
    "supported",
    "source",
    "sources",
    "proof",
    "link",
    "linked",
    "why",
)

STRUCTURED_SIGNALS = (
    "amount",
    "count",
    "status",
    "list",
    "which",
    "show",
    "how many",
    "total",
    "outstanding",
    "hold",
    "on hold",
    "paid",
    "payment",
    "invoice",
    "invoices",
    "budget",
    "budgets",
)

UNAPPROVED_TERM_ALIASES = {
    "vendor risk": "vendor-risk",
    "risk score": "vendor-risk",
    "vendor risk score": "vendor-risk",
}


def normalize_question_text(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[_\-]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


class QuestionAnalyzer:
    """Extract stable IDs, approved terms, and evidence intent without fetching data."""

    def __init__(self, definitions: tuple[BusinessTermDefinition, ...] = BUSINESS_DEFINITIONS) -> None:
        self._definitions = definitions

    def analyze(self, question: str) -> AnalyzedQuestion:
        normalized_question = normalize_question_text(question)
        entities = self._detect_entities(question)
        approved_terms = self._detect_approved_terms(normalized_question)
        unsupported_terms = self._detect_unsupported_terms(normalized_question, approved_terms)
        signals = self._detect_signals(normalized_question, approved_terms, unsupported_terms)
        intent = self._classify_intent(
            normalized_question=normalized_question,
            entities=entities,
            approved_terms=approved_terms,
            unsupported_terms=unsupported_terms,
            signals=signals,
        )

        return AnalyzedQuestion(
            question=question,
            normalized_question=normalized_question,
            intent=intent,
            entities=entities,
            approved_terms=approved_terms,
            signals=signals,
            unsupported_terms=unsupported_terms,
        )

    def _detect_entities(self, question: str) -> tuple[DetectedEntity, ...]:
        found: list[DetectedEntity] = []
        seen: set[tuple[EntityType, str]] = set()

        for entity_type, pattern in ENTITY_PATTERNS:
            for match in pattern.finditer(question):
                value = match.group(0).upper()
                key = (entity_type, value)
                if key not in seen:
                    seen.add(key)
                    found.append(DetectedEntity(entity_type=entity_type, value=value))

        return tuple(found)

    def _detect_approved_terms(self, normalized_question: str) -> tuple[ApprovedTermReference, ...]:
        matches: list[ApprovedTermReference] = []
        for definition in self._definitions:
            aliases = self._definition_aliases(definition)
            if any(self._contains_phrase(normalized_question, alias) for alias in aliases):
                matches.append(
                    ApprovedTermReference(
                        slug=definition.slug,
                        term=definition.term,
                        version=definition.version,
                    )
                )
        return tuple(matches)

    def _definition_aliases(self, definition: BusinessTermDefinition) -> tuple[str, ...]:
        aliases = {
            normalize_question_text(definition.term),
            normalize_question_text(definition.slug),
            *(normalize_question_text(alias) for alias in definition.synonyms),
        }
        return tuple(alias for alias in aliases if alias)

    def _detect_unsupported_terms(
        self,
        normalized_question: str,
        approved_terms: tuple[ApprovedTermReference, ...],
    ) -> tuple[str, ...]:
        if approved_terms:
            return ()

        unsupported = {
            slug
            for phrase, slug in UNAPPROVED_TERM_ALIASES.items()
            if self._contains_phrase(normalized_question, phrase)
        }
        return tuple(sorted(unsupported))

    def _detect_signals(
        self,
        normalized_question: str,
        approved_terms: tuple[ApprovedTermReference, ...],
        unsupported_terms: tuple[str, ...],
    ) -> tuple[QuestionSignal, ...]:
        signals: list[QuestionSignal] = []

        if approved_terms:
            signals.append(QuestionSignal.APPROVED_BUSINESS_TERM)
        if unsupported_terms:
            signals.append(QuestionSignal.UNAPPROVED_TERM)
        if any(self._contains_phrase(normalized_question, phrase) for phrase in DOCUMENT_SIGNALS):
            signals.append(QuestionSignal.DOCUMENT_MEANING)
        if any(self._contains_phrase(normalized_question, phrase) for phrase in RELATIONSHIP_SIGNALS):
            signals.append(QuestionSignal.RELATIONSHIP_TRACE)
        if any(self._contains_phrase(normalized_question, phrase) for phrase in LINKED_EVIDENCE_SIGNALS):
            signals.append(QuestionSignal.LINKED_RECORD_EVIDENCE)
        if any(self._contains_phrase(normalized_question, phrase) for phrase in STRUCTURED_SIGNALS):
            signals.append(QuestionSignal.EXACT_STRUCTURED_FACT)
        if (
            self._contains_phrase(normalized_question, "variance")
            and not approved_terms
            and not unsupported_terms
        ):
            signals.append(QuestionSignal.AMBIGUOUS_VARIANCE)

        return tuple(dict.fromkeys(signals))

    def _classify_intent(
        self,
        normalized_question: str,
        entities: tuple[DetectedEntity, ...],
        approved_terms: tuple[ApprovedTermReference, ...],
        unsupported_terms: tuple[str, ...],
        signals: tuple[QuestionSignal, ...],
    ) -> QuestionIntent:
        if unsupported_terms:
            return QuestionIntent.UNSUPPORTED

        if QuestionSignal.AMBIGUOUS_VARIANCE in signals:
            return QuestionIntent.AMBIGUOUS

        entity_types = {entity.entity_type for entity in entities}

        if EntityType.PROPERTY_ID in entity_types and QuestionSignal.RELATIONSHIP_TRACE in signals:
            return QuestionIntent.RELATIONSHIP_PATH

        if (
            EntityType.PROJECT_ID in entity_types
            and self._contains_phrase(normalized_question, "reconciliation")
            and QuestionSignal.LINKED_RECORD_EVIDENCE in signals
        ):
            return QuestionIntent.COMBINED_EVIDENCE

        if (
            EntityType.INVOICE_ID in entity_types
            and QuestionSignal.LINKED_RECORD_EVIDENCE in signals
            and approved_terms
        ):
            return QuestionIntent.COMBINED_EVIDENCE

        if EntityType.INVOICE_ID in entity_types and QuestionSignal.LINKED_RECORD_EVIDENCE in signals:
            return QuestionIntent.LINKED_EVIDENCE

        if EntityType.INVOICE_ID in entity_types and QuestionSignal.DOCUMENT_MEANING in signals:
            return QuestionIntent.LINKED_EVIDENCE

        if QuestionSignal.DOCUMENT_MEANING in signals and not self._has_only_structured_term(approved_terms):
            return QuestionIntent.DOCUMENT_ANSWER

        if EntityType.PROJECT_ID in entity_types and (
            approved_terms or QuestionSignal.EXACT_STRUCTURED_FACT in signals
        ):
            return QuestionIntent.STRUCTURED_CHECK

        if approved_terms and QuestionSignal.EXACT_STRUCTURED_FACT in signals:
            return QuestionIntent.STRUCTURED_CHECK

        return QuestionIntent.UNSUPPORTED

    def _has_only_structured_term(self, approved_terms: tuple[ApprovedTermReference, ...]) -> bool:
        structured_term_slugs = {"po-variance", "unpaid-invoice", "cost-code-over-budget"}
        return bool(approved_terms) and all(term.slug in structured_term_slugs for term in approved_terms)

    def _contains_phrase(self, normalized_question: str, phrase: str) -> bool:
        normalized_phrase = normalize_question_text(phrase)
        if not normalized_phrase:
            return False
        return re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_question) is not None
