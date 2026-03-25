"""Tests for SemanticRetriever — semantic context assembly for chapter generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiwebnovel.db.models import (
    ChapterPlan,
    Character,
    CharacterKnowledge,
    ContextRetrievalLog,
    Novel,
    StoryBibleEntry,
    User,
)
from aiwebnovel.db.vector import SearchResult
from aiwebnovel.story.semantic import SemanticRetriever

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession) -> User:
    user = User(
        email="semantic@test.com",
        hashed_password="hashed",
        role="author",
        is_anonymous=False,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_novel(session: AsyncSession, author_id: int) -> Novel:
    novel = Novel(author_id=author_id, title="Semantic Test Novel")
    session.add(novel)
    await session.flush()
    return novel


async def _create_character(
    session: AsyncSession, novel_id: int, name: str
) -> Character:
    char = Character(
        novel_id=novel_id,
        name=name,
        role="protagonist",
        description=f"{name} is a character.",
    )
    session.add(char)
    await session.flush()
    return char


async def _create_bible_entry(
    session: AsyncSession,
    novel_id: int,
    content: str,
    entry_type: str = "character_fact",
    source_chapter: int = 1,
    importance: int = 3,
    is_public: bool = True,
    entity_ids: list | None = None,
) -> StoryBibleEntry:
    entry = StoryBibleEntry(
        novel_id=novel_id,
        entry_type=entry_type,
        content=content,
        source_chapter=source_chapter,
        entity_ids=entity_ids or [],
        tags=[entry_type],
        importance=importance,
        is_public_knowledge=is_public,
        last_relevant_chapter=source_chapter,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _create_chapter_plan(
    session: AsyncSession,
    novel_id: int,
    chapter_number: int = 10,
) -> ChapterPlan:
    plan = ChapterPlan(
        novel_id=novel_id,
        chapter_number=chapter_number,
        title="The Battle Begins",
        scene_outline=[
            {"description": "Kai confronts the shadow beast in the forest"},
            {"description": "Sera arrives with reinforcements"},
        ],
        target_beats=["combat", "alliance"],
        target_tension=0.7,
    )
    session.add(plan)
    await session.flush()
    return plan


def _make_mock_llm():
    """Create a mock LLMProvider with embed method."""
    llm = MagicMock()
    llm.embed = AsyncMock(return_value=[[0.1] * 768])
    llm.estimate_tokens = MagicMock(side_effect=lambda text: len(text) // 4)
    return llm


def _make_mock_vector_store(results: list[SearchResult] | None = None):
    """Create a mock VectorStore with search method."""
    store = MagicMock()
    store.search = AsyncMock(return_value=results or [])
    return store


# ---------------------------------------------------------------------------
# Tests — build_query_from_plan
# ---------------------------------------------------------------------------


class TestBuildQueryFromPlan:
    """Test query string construction from chapter plans."""

    def test_extracts_title(self, test_settings):
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        plan = MagicMock()
        plan.title = "The Shadow Rises"
        plan.scene_outline = None
        plan.target_beats = None
        plan.plot_threads_advance = None
        plan.pov_character_id = None

        query = retriever.build_query_from_plan(plan)
        assert "The Shadow Rises" in query

    def test_extracts_scene_descriptions(self, test_settings):
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        plan = MagicMock()
        plan.title = "Battle"
        plan.scene_outline = [
            {"description": "Kai fights the dragon"},
            {"description": "Sera heals the wounded"},
        ]
        plan.target_beats = None
        plan.plot_threads_advance = None
        plan.pov_character_id = None

        query = retriever.build_query_from_plan(plan)
        assert "Kai fights the dragon" in query
        assert "Sera heals the wounded" in query

    def test_extracts_beats(self, test_settings):
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        plan = MagicMock()
        plan.title = "Test"
        plan.scene_outline = None
        plan.target_beats = ["revelation", "betrayal"]
        plan.plot_threads_advance = None
        plan.pov_character_id = None

        query = retriever.build_query_from_plan(plan)
        assert "revelation" in query
        assert "betrayal" in query

    def test_handles_none_fields(self, test_settings):
        """Plan with all None optional fields should still produce a query."""
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        plan = MagicMock()
        plan.title = "Minimal"
        plan.scene_outline = None
        plan.target_beats = None
        plan.plot_threads_advance = None
        plan.pov_character_id = None

        query = retriever.build_query_from_plan(plan)
        assert len(query) > 0


# ---------------------------------------------------------------------------
# Tests — assemble_semantic_context
# ---------------------------------------------------------------------------


class TestAssembleSemanticContext:
    """Test full semantic context assembly pipeline."""

    @pytest.fixture()
    async def novel_setup(self, db_session):
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")
        sera = await _create_character(db_session, novel.id, "Sera")
        plan = await _create_chapter_plan(db_session, novel.id, chapter_number=10)
        entries = [
            await _create_bible_entry(
                db_session, novel.id,
                "Kai is a fire mage with an ancient bloodline.",
                source_chapter=1, importance=4, entity_ids=[kai.id],
            ),
            await _create_bible_entry(
                db_session, novel.id,
                "Sera is a scholar of ice magic.",
                source_chapter=2, importance=3, entity_ids=[sera.id],
            ),
            await _create_bible_entry(
                db_session, novel.id,
                "The forest is home to shadow beasts.",
                entry_type="location_detail",
                source_chapter=3, importance=2,
            ),
        ]
        await db_session.flush()
        return novel, plan, entries, {"Kai": kai, "Sera": sera}

    async def test_returns_formatted_context(
        self, db_session, novel_setup, test_settings
    ):
        """assemble_semantic_context should return a SemanticContext with formatted text."""
        novel, plan, entries, _ = novel_setup

        search_results = [
            SearchResult(
                id=str(entries[0].id),
                text=entries[0].content,
                score=0.95,
                metadata={
                    "novel_id": novel.id,
                    "entry_type": "character_fact",
                    "chapter": 1,
                    "importance": 4,
                    "entity_ids": [],
                },
            ),
            SearchResult(
                id=str(entries[1].id),
                text=entries[1].content,
                score=0.80,
                metadata={
                    "novel_id": novel.id,
                    "entry_type": "character_fact",
                    "chapter": 2,
                    "importance": 3,
                    "entity_ids": [],
                },
            ),
        ]

        llm = _make_mock_llm()
        store = _make_mock_vector_store(search_results)
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        ctx = await retriever.assemble_semantic_context(
            session=db_session,
            novel_id=novel.id,
            chapter_plan=plan,
            token_budget=3000,
        )

        assert ctx.formatted_text is not None
        assert len(ctx.formatted_text) > 0
        assert ctx.total_tokens > 0

    async def test_calls_embed(self, db_session, novel_setup, test_settings):
        """assemble_semantic_context should call llm.embed with the query."""
        novel, plan, entries, _ = novel_setup

        llm = _make_mock_llm()
        store = _make_mock_vector_store([])
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        await retriever.assemble_semantic_context(
            session=db_session,
            novel_id=novel.id,
            chapter_plan=plan,
        )

        llm.embed.assert_called_once()

    async def test_token_budget_respected(
        self, db_session, novel_setup, test_settings
    ):
        """Total tokens should not exceed the budget."""
        novel, plan, entries, _ = novel_setup

        # Create many search results
        search_results = [
            SearchResult(
                id=str(entries[i].id),
                text=entries[i].content * 10,  # Make entries large
                score=0.9 - i * 0.1,
                metadata={
                    "novel_id": novel.id,
                    "entry_type": "character_fact",
                    "chapter": i + 1,
                    "importance": 3,
                    "entity_ids": [],
                },
            )
            for i in range(len(entries))
        ]

        llm = _make_mock_llm()
        store = _make_mock_vector_store(search_results)
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        ctx = await retriever.assemble_semantic_context(
            session=db_session,
            novel_id=novel.id,
            chapter_plan=plan,
            token_budget=100,  # Very small budget
        )

        assert ctx.total_tokens <= 100

    async def test_retrieval_logged(
        self, db_session, novel_setup, test_settings
    ):
        """Retrieval should be logged to ContextRetrievalLog."""
        novel, plan, entries, _ = novel_setup

        search_results = [
            SearchResult(
                id=str(entries[0].id),
                text=entries[0].content,
                score=0.95,
                metadata={
                    "novel_id": novel.id,
                    "entry_type": "character_fact",
                    "chapter": 1,
                    "importance": 4,
                    "entity_ids": [],
                },
            ),
        ]

        llm = _make_mock_llm()
        store = _make_mock_vector_store(search_results)
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        ctx = await retriever.assemble_semantic_context(
            session=db_session,
            novel_id=novel.id,
            chapter_plan=plan,
        )

        assert ctx.retrieval_log_id is not None

        # Verify log in DB
        result = await db_session.execute(
            select(ContextRetrievalLog).where(
                ContextRetrievalLog.id == ctx.retrieval_log_id
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.novel_id == novel.id

    async def test_empty_results_returns_empty_context(
        self, db_session, novel_setup, test_settings
    ):
        """No search results should produce an empty context."""
        novel, plan, _, _ = novel_setup

        llm = _make_mock_llm()
        store = _make_mock_vector_store([])
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        ctx = await retriever.assemble_semantic_context(
            session=db_session,
            novel_id=novel.id,
            chapter_plan=plan,
        )

        assert ctx.entries == []
        assert ctx.total_tokens == 0


# ---------------------------------------------------------------------------
# Tests — composite scoring
# ---------------------------------------------------------------------------


class TestCompositeScoring:
    """Test the composite scoring formula."""

    def test_scoring_formula(self, test_settings):
        """Verify composite score calculation."""
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        score = retriever._compute_composite_score(
            semantic_similarity=0.9,
            chapters_since=2,
            importance=4,
            narrative_pressure=0.5,
        )

        # 0.40 * 0.9 + 0.25 * (1/(1+2)) + 0.20 * (4/5) + 0.15 * 0.5
        expected = 0.40 * 0.9 + 0.25 * (1.0 / 3.0) + 0.20 * (4.0 / 5.0) + 0.15 * 0.5
        assert abs(score - expected) < 0.001

    def test_recency_boost_decays(self, test_settings):
        """More chapters since relevant should decrease score."""
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        recent = retriever._compute_composite_score(
            semantic_similarity=0.9,
            chapters_since=0,
            importance=3,
            narrative_pressure=0.0,
        )
        old = retriever._compute_composite_score(
            semantic_similarity=0.9,
            chapters_since=50,
            importance=3,
            narrative_pressure=0.0,
        )

        assert recent > old

    def test_importance_boosts_score(self, test_settings):
        """Higher importance should increase score."""
        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        high = retriever._compute_composite_score(
            semantic_similarity=0.5,
            chapters_since=5,
            importance=5,
            narrative_pressure=0.0,
        )
        low = retriever._compute_composite_score(
            semantic_similarity=0.5,
            chapters_since=5,
            importance=1,
            narrative_pressure=0.0,
        )

        assert high > low


# ---------------------------------------------------------------------------
# Tests — character knowledge filtering
# ---------------------------------------------------------------------------


class TestCharacterKnowledgeFiltering:
    """Test that character knowledge filters entries correctly."""

    async def test_filter_by_character_knowledge(
        self, db_session, test_settings
    ):
        user = await _create_user(db_session)
        novel = await _create_novel(db_session, user.id)
        kai = await _create_character(db_session, novel.id, "Kai")

        entry1 = await _create_bible_entry(
            db_session, novel.id, "Known fact", entity_ids=[kai.id]
        )
        entry2 = await _create_bible_entry(
            db_session, novel.id, "Unknown fact", entity_ids=[kai.id]
        )

        # Kai knows entry1 but not entry2
        knowledge = CharacterKnowledge(
            character_id=kai.id,
            bible_entry_id=entry1.id,
            knows=True,
            knowledge_level="full",
            learned_at_chapter=1,
            source="witnessed",
        )
        db_session.add(knowledge)
        await db_session.flush()

        llm = _make_mock_llm()
        store = _make_mock_vector_store()
        retriever = SemanticRetriever(llm=llm, vector_store=store, settings=test_settings)

        known_ids = await retriever.get_character_filtered_entries(
            session=db_session,
            character_id=kai.id,
            entry_ids=[entry1.id, entry2.id],
        )

        assert entry1.id in known_ids
        assert entry2.id not in known_ids
