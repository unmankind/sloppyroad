"""Character seeding from world generation data.

Extracted from pipeline.py to reduce module size.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import Character

logger = structlog.get_logger(__name__)


class CharacterSeeder:
    """Creates Character rows from world generation stage data."""

    @staticmethod
    def _parse_stage_data(data: Any) -> dict:
        """Normalise stage data that may be a JSON string or already a dict."""
        if isinstance(data, str):
            return json.loads(data)
        if isinstance(data, dict):
            return data
        return {}

    async def seed_characters_from_world(
        self,
        session: AsyncSession,
        novel_id: int,
        stage_data: dict[str, Any],
        char_identities: dict[str, list[Any]] | None = None,
        has_custom_direction: bool = False,
    ) -> None:
        """Create Character rows from protagonist / antagonists / supporting_cast.

        If char_identities is provided (from name generator), populates
        sex, pronouns, physical_traits, and visual_appearance on each
        Character row by matching pre-rolled names.

        When has_custom_direction is True, LLM-generated visual_appearance
        takes priority over pre-rolled identity traits, since the LLM had
        the author's direction as context.

        Idempotent — skips if characters already exist for this novel.
        """
        existing = (await session.execute(
            select(func.count()).select_from(Character).where(
                Character.novel_id == novel_id,
            )
        )).scalar_one()
        if existing > 0:
            logger.info("character_seed_skipped_already_exist",
                        novel_id=novel_id, count=existing)
            return

        created: list[str] = []

        # Build lookup from pre-rolled identities by name
        _identity_by_name: dict[str, Any] = {}
        if char_identities:
            for role_list in char_identities.values():
                for identity in role_list:
                    _identity_by_name[identity.full_name.lower()] = identity

        def _identity_fields(name: str) -> dict[str, Any]:
            """Get sex/pronouns/traits/appearance from pre-rolled identity."""
            ident = _identity_by_name.get(name.lower())
            if ident is None:
                return {}
            traits_str = ", ".join(ident.physical_traits)
            return {
                "sex": ident.sex,
                "pronouns": ident.pronouns,
                "physical_traits": ident.physical_traits,
                "visual_appearance": (
                    f"{ident.sex.title()} ({ident.pronouns}). "
                    f"{traits_str.capitalize()}."
                ),
            }

        def _pick_visual(
            id_fields: dict[str, Any], llm_data: dict,
        ) -> str | None:
            """Pick visual_appearance with correct priority.

            With custom direction: LLM wins (it had author context).
            Without: pre-rolled identity wins (diversity guarantee).
            """
            pre_rolled = id_fields.get("visual_appearance")
            llm_visual = llm_data.get("visual_appearance") or None
            if has_custom_direction:
                return llm_visual or pre_rolled
            return pre_rolled or llm_visual

        # --- Protagonist ---
        proto = self._parse_stage_data(stage_data.get("protagonist", {}))
        if proto.get("name"):
            personality = proto.get("personality", {})
            traits = personality.get("core_traits", []) if isinstance(personality, dict) else []
            motivation = proto.get("motivation", "")
            if isinstance(motivation, dict):
                motivation = motivation.get("surface_motivation", "")

            id_fields = _identity_fields(proto["name"])
            session.add(Character(
                novel_id=novel_id,
                name=proto["name"],
                role="protagonist",
                description=proto.get("background", ""),
                visual_appearance=_pick_visual(id_fields, proto),
                sex=id_fields.get("sex"),
                pronouns=id_fields.get("pronouns"),
                physical_traits=id_fields.get("physical_traits"),
                personality_traits=traits,
                background=proto.get("background"),
                motivation=str(motivation),
                current_goal=proto.get("initial_circumstances"),
            ))
            created.append(proto["name"])

        # --- Antagonists ---
        antag_data = self._parse_stage_data(stage_data.get("antagonists", {}))
        antagonists = antag_data.get("antagonists", [])
        if isinstance(antag_data, list):
            antagonists = antag_data
        for antag in antagonists:
            if not isinstance(antag, dict) or not antag.get("name"):
                continue
            motivation = antag.get("motivation", "")
            if isinstance(motivation, dict):
                motivation = motivation.get("surface_motivation", "")
            id_fields = _identity_fields(antag["name"])
            session.add(Character(
                novel_id=novel_id,
                name=antag["name"],
                role="antagonist",
                description=antag.get("relationship_to_protagonist", ""),
                motivation=str(motivation),
                sex=id_fields.get("sex"),
                pronouns=id_fields.get("pronouns"),
                physical_traits=id_fields.get("physical_traits"),
                visual_appearance=_pick_visual(id_fields, antag),
            ))
            created.append(antag["name"])

        # --- Supporting Cast ---
        support_data = self._parse_stage_data(stage_data.get("supporting_cast", {}))
        characters = support_data.get("characters", [])
        if isinstance(support_data, list):
            characters = support_data
        for char in characters:
            if not isinstance(char, dict) or not char.get("name"):
                continue
            id_fields = _identity_fields(char["name"])
            session.add(Character(
                novel_id=novel_id,
                name=char["name"],
                role="supporting",
                description=char.get("narrative_purpose", ""),
                background=char.get("connection_to_protagonist"),
                sex=id_fields.get("sex"),
                pronouns=id_fields.get("pronouns"),
                physical_traits=id_fields.get("physical_traits"),
                visual_appearance=_pick_visual(id_fields, char),
            ))
            created.append(char["name"])

        if created:
            await session.flush()
            logger.info("characters_seeded_from_world",
                        novel_id=novel_id, count=len(created), names=created)
