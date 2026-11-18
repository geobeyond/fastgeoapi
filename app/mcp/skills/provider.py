"""The provider that serves the OGC API skills an OpenAPI document selects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp.skills import Skill
from fastmcp.skills.provider import SkillCatalogProvider

from app.mcp.skills.requirements import SKILL_REQUIREMENTS, SKILLS_DIRECTORY
from app.mcp.skills.selection import select_skills


class OgcApiSkillProvider(SkillCatalogProvider):
    """Serve the skills that teach the operations an OpenAPI document has.

    The skill folders are read once, when the provider is built. Each
    request serves the skills of the last document passed to
    :meth:`select`, so a reload changes them without reading the folders
    again.
    """

    def __init__(self, openapi_spec: Mapping[str, Any]) -> None:
        """Read the skill folders and select the skills of a document.

        Parameters
        ----------
        openapi_spec
            The OpenAPI document the MCP tools are generated from.
        """
        super().__init__()
        self._files = {
            requirement.name: dict(Skill.from_directory(SKILLS_DIRECTORY / requirement.name).files)
            for requirement in SKILL_REQUIREMENTS
        }
        self._selected: tuple[Skill, ...] = ()
        self.select(openapi_spec)

    def select(self, openapi_spec: Mapping[str, Any]) -> None:
        """Replace the served skills with the ones a document selects.

        Parameters
        ----------
        openapi_spec
            The OpenAPI document the MCP tools are generated from.
        """
        chosen = select_skills(openapi_spec, SKILL_REQUIREMENTS)
        selected = []
        for requirement in SKILL_REQUIREMENTS:
            if requirement.name not in chosen:
                continue
            left_out = set(requirement.files) - chosen[requirement.name]
            files = {
                path: content
                for path, content in self._files[requirement.name].items()
                if path not in left_out
            }
            selected.append(Skill.from_files(files))
        self._selected = tuple(selected)

    async def load_skills(self) -> tuple[Skill, ...]:
        """Get the skills selected by the last document.

        Returns
        -------
        tuple[Skill, ...]
            The selected skills, each without the optional files the
            document does not need.
        """
        return self._selected
