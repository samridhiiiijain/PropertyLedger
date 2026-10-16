from __future__ import annotations

from .definitions import BUSINESS_DEFINITIONS, BusinessTermDefinition


class BusinessDefinitionService:
    def list_definitions(self) -> tuple[BusinessTermDefinition, ...]:
        return BUSINESS_DEFINITIONS

    def get_definition(self, slug: str) -> BusinessTermDefinition | None:
        normalized = slug.strip().lower()
        for definition in BUSINESS_DEFINITIONS:
            if definition.slug == normalized:
                return definition
        return None
