"""SQLAlchemy 2.0 ORM models for AIWN 2.0.

This is the canonical data layer. Every table the application needs is
defined here using modern ``Mapped[type]`` / ``mapped_column()`` style.

Sections are organised by domain and match the systems described in
ARCHITECTURE.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all models."""

    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


# ═══════════════════════════════════════════════════════════════════════════
# USERS & AUTH (System 9)
# ═══════════════════════════════════════════════════════════════════════════


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(20), default="local")
    hashed_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="reader")  # author / reader / admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True)
    cookie_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Email verification
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True
    )
    email_verification_token_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    # relationships
    author_profile: Mapped[Optional[AuthorProfile]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False,
    )
    reader_profile: Mapped[Optional[ReaderProfile]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False,
    )
    novels: Mapped[list[Novel]] = relationship(
        back_populates="author", cascade="all, delete-orphan",
    )
    bookmarks: Mapped[list[ReaderBookmark]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    llm_usage_logs: Mapped[list[LLMUsageLog]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    api_keys: Mapped[list[AuthorAPIKey]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_users_email", "email", postgresql_where="email IS NOT NULL"),
        Index(
            "idx_users_cookie_token",
            "cookie_token",
            postgresql_where="cookie_token IS NOT NULL",
        ),
        Index(
            "idx_users_verification_token",
            "email_verification_token",
            postgresql_where="email_verification_token IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


class AuthorProfile(Base):
    __tablename__ = "author_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="trial")
    api_budget_cents: Mapped[int] = mapped_column(Integer, default=500)
    api_spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    image_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    image_spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    default_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    default_image_generation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    plan_type: Mapped[str] = mapped_column(String(20), default="free")  # free/byok/admin
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="author_profile")

    def __repr__(self) -> str:
        return f"<AuthorProfile id={self.id} user_id={self.user_id}>"


class ReaderProfile(Base):
    __tablename__ = "reader_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reading_preferences: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="reader_profile")

    def __repr__(self) -> str:
        return f"<ReaderProfile id={self.id} user_id={self.user_id}>"


class ReaderBookmark(Base):
    __tablename__ = "reader_bookmarks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    last_chapter_read: Mapped[int] = mapped_column(Integer, default=0)
    scroll_position: Mapped[float] = mapped_column(Float, default=0.0)
    notify_on_update: Mapped[bool] = mapped_column(Boolean, default=False)
    last_notified_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="bookmarks")
    novel: Mapped[Novel] = relationship(back_populates="bookmarks")

    __table_args__ = (
        UniqueConstraint("user_id", "novel_id", name="uq_reader_bookmark_user_novel"),
        Index("idx_reader_bookmarks_user", "user_id"),
        Index("idx_reader_bookmarks_notify", "novel_id", "notify_on_update"),
    )

    def __repr__(self) -> str:
        return f"<ReaderBookmark user_id={self.user_id} novel_id={self.novel_id}>"


# ═══════════════════════════════════════════════════════════════════════════
# CORE
# ═══════════════════════════════════════════════════════════════════════════


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(500))
    genre: Mapped[str] = mapped_column(String(100), default="progression_fantasy")
    status: Mapped[str] = mapped_column(
        String(30), default="skeleton_pending",
    )
    # skeleton_pending/skeleton_in_progress/skeleton_complete/
    # writing/writing_paused/writing_complete/complete
    autonomous_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    autonomous_cadence_hours: Mapped[int] = mapped_column(Integer, default=24)
    autonomous_daily_budget_cents: Mapped[int] = mapped_column(Integer, default=100)
    autonomous_skip_arc_boundaries: Mapped[bool] = mapped_column(Boolean, default=False)
    image_budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    image_spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completion_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    share_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    # relationships
    author: Mapped[User] = relationship(back_populates="novels")
    settings: Mapped[Optional[NovelSettings]] = relationship(
        back_populates="novel", cascade="all, delete-orphan", uselist=False,
    )
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    chapter_drafts: Mapped[list[ChapterDraft]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    world_building_stages: Mapped[list[WorldBuildingStage]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    cosmology: Mapped[Optional[Cosmology]] = relationship(
        back_populates="novel", cascade="all, delete-orphan", uselist=False,
    )
    regions: Mapped[list[Region]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
        foreign_keys="Region.novel_id",
    )
    factions: Mapped[list[Faction]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
        foreign_keys="Faction.novel_id",
    )
    historical_events: Mapped[list[HistoricalEvent]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    characters: Mapped[list[Character]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
        foreign_keys="Character.novel_id",
    )
    power_system: Mapped[Optional[PowerSystem]] = relationship(
        back_populates="novel", cascade="all, delete-orphan", uselist=False,
    )
    arc_plans: Mapped[list[ArcPlan]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    chapter_plans: Mapped[list[ChapterPlan]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    plot_threads: Mapped[list[PlotThread]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    scope_tiers: Mapped[list[ScopeTier]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    escalation_states: Mapped[list[EscalationState]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    foreshadowing_seeds: Mapped[list[ForeshadowingSeed]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    tension_trackers: Mapped[list[TensionTracker]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    story_bible_entries: Mapped[list[StoryBibleEntry]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
        foreign_keys="StoryBibleEntry.novel_id",
    )
    context_retrieval_logs: Mapped[list[ContextRetrievalLog]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    perspective_divergences: Mapped[list[PerspectiveDivergence]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    chekhov_guns: Mapped[list[ChekhovGun]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    art_assets: Mapped[list[ArtAsset]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    art_style_guides: Mapped[list[ArtStyleGuide]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    art_generation_queue: Mapped[list[ArtGenerationQueue]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    reader_signals: Mapped[list[ReaderSignal]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    oracle_questions: Mapped[list[OracleQuestion]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    butterfly_choices: Mapped[list[ButterflyChoice]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    faction_alignments: Mapped[list[FactionAlignment]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    llm_usage_logs: Mapped[list[LLMUsageLog]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    image_usage_logs: Mapped[list[ImageUsageLog]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    generation_jobs: Mapped[list[GenerationJob]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    novel_stats: Mapped[Optional[NovelStats]] = relationship(
        back_populates="novel", cascade="all, delete-orphan", uselist=False,
    )
    novel_ratings: Mapped[list[NovelRating]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    novel_tags: Mapped[list[NovelTag]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    novel_seeds: Mapped[list[NovelSeed]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    bookmarks: Mapped[list[ReaderBookmark]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )
    novel_access: Mapped[Optional[NovelAccess]] = relationship(
        back_populates="novel", cascade="all, delete-orphan", uselist=False,
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="novel", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_novels_author", "author_id"),
    )

    def __repr__(self) -> str:
        return f"<Novel id={self.id} title={self.title!r} status={self.status!r}>"


class NovelSettings(Base):
    __tablename__ = "novel_settings"

    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True,
    )
    planning_mode: Mapped[str] = mapped_column(
        String(20), default="supervised",
    )  # autonomous/supervised/collaborative
    pov_mode: Mapped[str] = mapped_column(String(20), default="single")  # single/rotating/multi
    content_rating: Mapped[str] = mapped_column(String(20), default="teen")
    target_chapter_length: Mapped[int] = mapped_column(Integer, default=5000)
    target_chapter_length_min: Mapped[int] = mapped_column(Integer, default=3000)
    target_chapter_length_max: Mapped[int] = mapped_column(Integer, default=5000)
    default_temperature: Mapped[float] = mapped_column(Float, default=0.7)
    generation_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    analysis_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reader_influence_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    image_generation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    art_style_preset: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    custom_genre_conventions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_scope_tiers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    autonomous_generation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    autonomous_cadence_hours: Mapped[int] = mapped_column(Integer, default=24)
    autonomous_skip_arc_boundaries: Mapped[bool] = mapped_column(Boolean, default=False)
    autonomous_daily_budget_cents: Mapped[int] = mapped_column(Integer, default=100)
    last_autonomous_generation_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    autonomous_consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="settings")

    def __repr__(self) -> str:
        return f"<NovelSettings novel_id={self.novel_id} mode={self.planning_mode!r}>"


class NovelAccess(Base):
    __tablename__ = "novel_access"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), unique=True,
    )
    access_type: Mapped[str] = mapped_column(String(20), default="private")
    share_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="novel_access")

    def __repr__(self) -> str:
        return f"<NovelAccess novel_id={self.novel_id} type={self.access_type!r}>"


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    arc_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arc_plans.id", ondelete="SET NULL"), nullable=True,
    )
    chapter_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    chapter_text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pov_character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True,
    )
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    generation_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    is_bridge: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="chapters")
    arc_plan: Mapped[Optional[ArcPlan]] = relationship(back_populates="chapters")
    pov_character: Mapped[Optional[Character]] = relationship(
        back_populates="pov_chapters", foreign_keys=[pov_character_id],
    )
    summaries: Mapped[list[ChapterSummary]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan",
    )
    chapter_pov: Mapped[Optional[ChapterPOV]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", uselist=False,
    )
    images: Mapped[list[ChapterImage]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan",
        order_by="ChapterImage.paragraph_index",
    )

    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_number", name="uq_chapter_novel_number"),
    )

    def __repr__(self) -> str:
        return f"<Chapter id={self.id} novel_id={self.novel_id} num={self.chapter_number}>"


class ChapterSummary(Base):
    __tablename__ = "chapter_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    summary_type: Mapped[str] = mapped_column(
        String(30), default="standard",
    )  # standard/arc/power_focused/relationship_focused/enhanced_recap
    content: Mapped[str] = mapped_column(Text)
    key_events: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    emotional_arc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cliffhangers: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    chapter: Mapped[Chapter] = relationship(back_populates="summaries")

    __table_args__ = (
        UniqueConstraint("chapter_id", "summary_type", name="uq_summary_chapter_type"),
    )

    def __repr__(self) -> str:
        return f"<ChapterSummary id={self.id} type={self.summary_type!r}>"


class ChapterDraft(Base):
    __tablename__ = "chapter_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True,
    )
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_number: Mapped[int] = mapped_column(Integer)
    draft_number: Mapped[int] = mapped_column(Integer)
    chapter_text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    model_used: Mapped[str] = mapped_column(String(100))
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    generation_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_guidance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="chapter_drafts")
    chapter: Mapped[Optional[Chapter]] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "novel_id", "chapter_number", "draft_number",
            name="uq_draft_novel_chapter_draft",
        ),
        Index("idx_chapter_drafts_novel_chapter", "novel_id", "chapter_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChapterDraft id={self.id} novel={self.novel_id} "
            f"ch={self.chapter_number} draft={self.draft_number}>"
        )


class ChapterImage(Base):
    """Join table linking chapters to inline scene illustrations."""

    __tablename__ = "chapter_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    art_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("art_assets.id", ondelete="SET NULL"), nullable=True,
    )
    paragraph_index: Mapped[int] = mapped_column(Integer)
    scene_description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="pending",
    )  # pending / generating / complete / failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    chapter: Mapped[Chapter] = relationship(back_populates="images")
    art_asset: Mapped[Optional[ArtAsset]] = relationship()

    __table_args__ = (
        Index("idx_chapter_images_chapter", "chapter_id"),
    )

    def __repr__(self) -> str:
        return f"<ChapterImage id={self.id} ch={self.chapter_id} para={self.paragraph_index}>"


class WorldBuildingStage(Base):
    __tablename__ = "world_building_stages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    stage_order: Mapped[int] = mapped_column(Integer)
    stage_name: Mapped[str] = mapped_column(String(50))
    prompt_used: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[str] = mapped_column(Text)
    parsed_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    model_used: Mapped[str] = mapped_column(String(100))
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="world_building_stages")

    __table_args__ = (
        UniqueConstraint("novel_id", "stage_order", name="uq_wbs_novel_stage"),
    )

    def __repr__(self) -> str:
        return f"<WorldBuildingStage id={self.id} stage={self.stage_name!r}>"


# ═══════════════════════════════════════════════════════════════════════════
# WORLD
# ═══════════════════════════════════════════════════════════════════════════


class Cosmology(Base):
    __tablename__ = "cosmology"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), unique=True)
    fundamental_forces: Mapped[list[Any]] = mapped_column(JSON)
    planes_of_existence: Mapped[list[Any]] = mapped_column(JSON)
    creation_myth: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cosmic_laws: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    energy_types: Mapped[list[Any]] = mapped_column(JSON)
    reality_tiers: Mapped[list[Any]] = mapped_column(JSON)

    novel: Mapped[Novel] = relationship(back_populates="cosmology")

    def __repr__(self) -> str:
        return f"<Cosmology id={self.id} novel_id={self.novel_id}>"


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    visual_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geography_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    parent_region_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), nullable=True,
    )
    climate: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notable_features: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    scope_tier: Mapped[int] = mapped_column(Integer, default=1)
    revealed_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="regions", foreign_keys=[novel_id])
    parent_region: Mapped[Optional[Region]] = relationship(
        remote_side="Region.id", foreign_keys=[parent_region_id],
    )
    factions: Mapped[list[Faction]] = relationship(
        back_populates="territory_region", foreign_keys="Faction.territory_region_id",
    )
    characters: Mapped[list[Character]] = relationship(
        back_populates="current_region", foreign_keys="Character.current_region_id",
    )

    def __repr__(self) -> str:
        return f"<Region id={self.id} name={self.name!r}>"


class Faction(Base):
    __tablename__ = "factions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    visual_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ideology: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    power_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    territory_region_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), nullable=True,
    )
    leader_character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True,
    )
    scope_tier: Mapped[int] = mapped_column(Integer, default=1)
    goals: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    resources: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="factions", foreign_keys=[novel_id])
    territory_region: Mapped[Optional[Region]] = relationship(
        back_populates="factions", foreign_keys=[territory_region_id],
    )
    leader: Mapped[Optional[Character]] = relationship(
        foreign_keys=[leader_character_id],
    )
    members: Mapped[list[Character]] = relationship(
        back_populates="faction", foreign_keys="Character.faction_id",
    )
    faction_alignments: Mapped[list[FactionAlignment]] = relationship(
        back_populates="faction", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Faction id={self.id} name={self.name!r}>"


class HistoricalEvent(Base):
    __tablename__ = "historical_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    era: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    chronological_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    impact: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    related_region_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), nullable=True,
    )
    related_faction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("factions.id", ondelete="SET NULL"), nullable=True,
    )
    is_common_knowledge: Mapped[bool] = mapped_column(Boolean, default=True)
    scope_tier: Mapped[int] = mapped_column(Integer, default=1)

    novel: Mapped[Novel] = relationship(back_populates="historical_events")

    def __repr__(self) -> str:
        return f"<HistoricalEvent id={self.id} name={self.name!r}>"


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    # protagonist/antagonist/mentor/ally/rival/neutral
    role: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    sex: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pronouns: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    physical_traits: Mapped[Optional[list[Any]]] = mapped_column(
        JSON, nullable=True,
    )
    visual_appearance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    personality_traits: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    background: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    motivation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    faction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("factions.id", ondelete="SET NULL", use_alter=True), nullable=True,
    )
    current_region_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), nullable=True,
    )
    scope_tier: Mapped[int] = mapped_column(Integer, default=1)
    introduced_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True)
    arc_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="characters", foreign_keys=[novel_id])
    faction: Mapped[Optional[Faction]] = relationship(
        back_populates="members", foreign_keys=[faction_id],
    )
    current_region: Mapped[Optional[Region]] = relationship(
        back_populates="characters", foreign_keys=[current_region_id],
    )
    power_profile: Mapped[Optional[CharacterPowerProfile]] = relationship(
        back_populates="character", cascade="all, delete-orphan", uselist=False,
    )
    abilities: Mapped[list[CharacterAbility]] = relationship(
        back_populates="character", cascade="all, delete-orphan",
    )
    power_sources: Mapped[list[CharacterPowerSource]] = relationship(
        back_populates="character", cascade="all, delete-orphan",
    )
    advancement_events: Mapped[list[AdvancementEvent]] = relationship(
        back_populates="character", cascade="all, delete-orphan",
    )
    worldview: Mapped[Optional[CharacterWorldview]] = relationship(
        back_populates="character", cascade="all, delete-orphan", uselist=False,
    )
    narrative_voice: Mapped[Optional[NarrativeVoice]] = relationship(
        back_populates="character", cascade="all, delete-orphan", uselist=False,
    )
    knowledge: Mapped[list[CharacterKnowledge]] = relationship(
        back_populates="character", cascade="all, delete-orphan",
    )
    pov_chapters: Mapped[list[Chapter]] = relationship(
        back_populates="pov_character", foreign_keys="Chapter.pov_character_id",
    )

    def __repr__(self) -> str:
        return f"<Character id={self.id} name={self.name!r} role={self.role!r}>"


class CharacterRelationship(Base):
    __tablename__ = "character_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_a_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    character_b_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    relationship_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intensity: Mapped[float] = mapped_column(Float, default=5.0)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    established_at_chapter: Mapped[int] = mapped_column(Integer)
    last_interaction_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)

    character_a: Mapped[Character] = relationship(foreign_keys=[character_a_id])
    character_b: Mapped[Character] = relationship(foreign_keys=[character_b_id])

    __table_args__ = (
        CheckConstraint("character_a_id < character_b_id", name="ck_char_rel_ordering"),
        UniqueConstraint("character_a_id", "character_b_id", name="uq_char_rel_pair"),
        Index("idx_char_rel_a", "character_a_id"),
        Index("idx_char_rel_b", "character_b_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CharacterRelationship {self.character_a_id}<->"
            f"{self.character_b_id} type={self.relationship_type!r}>"
        )


class FactionRelationship(Base):
    __tablename__ = "faction_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    faction_a_id: Mapped[int] = mapped_column(
        ForeignKey("factions.id", ondelete="CASCADE"),
    )
    faction_b_id: Mapped[int] = mapped_column(
        ForeignKey("factions.id", ondelete="CASCADE"),
    )
    relationship_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intensity: Mapped[float] = mapped_column(Float, default=0.5)
    established_at_chapter: Mapped[int] = mapped_column(Integer)
    last_updated_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    faction_a: Mapped[Faction] = relationship(foreign_keys=[faction_a_id])
    faction_b: Mapped[Faction] = relationship(foreign_keys=[faction_b_id])

    __table_args__ = (
        CheckConstraint("faction_a_id < faction_b_id", name="ck_faction_rel_ordering"),
        UniqueConstraint("faction_a_id", "faction_b_id", name="uq_faction_rel_pair"),
        Index("idx_faction_rel_a", "faction_a_id"),
        Index("idx_faction_rel_b", "faction_b_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<FactionRelationship {self.faction_a_id}<->"
            f"{self.faction_b_id} type={self.relationship_type!r}>"
        )


# ═══════════════════════════════════════════════════════════════════════════
# POWER SYSTEM (System 2)
# ═══════════════════════════════════════════════════════════════════════════


class PowerSystem(Base):
    __tablename__ = "power_systems"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), unique=True)
    system_name: Mapped[str] = mapped_column(String(200))
    core_mechanic: Mapped[str] = mapped_column(Text)
    energy_source: Mapped[str] = mapped_column(Text)
    advancement_mechanics: Mapped[dict[str, Any]] = mapped_column(JSON)
    hard_limits: Mapped[list[Any]] = mapped_column(JSON)
    soft_limits: Mapped[list[Any]] = mapped_column(JSON)
    power_ceiling: Mapped[str] = mapped_column(Text)

    novel: Mapped[Novel] = relationship(back_populates="power_system")
    ranks: Mapped[list[PowerRank]] = relationship(
        back_populates="power_system", cascade="all, delete-orphan",
    )
    disciplines: Mapped[list[PowerDiscipline]] = relationship(
        back_populates="power_system", cascade="all, delete-orphan",
    )
    abilities: Mapped[list[Ability]] = relationship(
        back_populates="power_system", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PowerSystem id={self.id} name={self.system_name!r}>"


class PowerRank(Base):
    __tablename__ = "power_ranks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    power_system_id: Mapped[int] = mapped_column(
        ForeignKey("power_systems.id", ondelete="CASCADE"),
    )
    rank_name: Mapped[str] = mapped_column(String(100))
    rank_order: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    typical_capabilities: Mapped[str] = mapped_column(Text)
    advancement_requirements: Mapped[str] = mapped_column(Text)
    advancement_bottleneck: Mapped[str] = mapped_column(Text)
    population_ratio: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    qualitative_shift: Mapped[str] = mapped_column(Text)
    scope_tier: Mapped[int] = mapped_column(Integer, default=1)

    power_system: Mapped[PowerSystem] = relationship(back_populates="ranks")

    __table_args__ = (
        UniqueConstraint("power_system_id", "rank_order", name="uq_rank_system_order"),
    )

    def __repr__(self) -> str:
        return f"<PowerRank id={self.id} name={self.rank_name!r} order={self.rank_order}>"


class PowerDiscipline(Base):
    __tablename__ = "power_disciplines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    power_system_id: Mapped[int] = mapped_column(
        ForeignKey("power_systems.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(200))
    philosophy: Mapped[str] = mapped_column(Text)
    source_energy: Mapped[str] = mapped_column(Text)
    strengths: Mapped[list[Any]] = mapped_column(JSON)
    weaknesses: Mapped[list[Any]] = mapped_column(JSON)
    typical_practitioners: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    power_system: Mapped[PowerSystem] = relationship(back_populates="disciplines")

    __table_args__ = (
        UniqueConstraint("power_system_id", "name", name="uq_discipline_system_name"),
    )

    def __repr__(self) -> str:
        return f"<PowerDiscipline id={self.id} name={self.name!r}>"


class DisciplineSynergy(Base):
    __tablename__ = "discipline_synergies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    discipline_a_id: Mapped[int] = mapped_column(
        ForeignKey("power_disciplines.id", ondelete="CASCADE"),
    )
    discipline_b_id: Mapped[int] = mapped_column(
        ForeignKey("power_disciplines.id", ondelete="CASCADE"),
    )
    synergy_description: Mapped[str] = mapped_column(Text)
    emergent_capability: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    known_practitioners: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    discipline_a: Mapped[PowerDiscipline] = relationship(foreign_keys=[discipline_a_id])
    discipline_b: Mapped[PowerDiscipline] = relationship(foreign_keys=[discipline_b_id])

    __table_args__ = (
        CheckConstraint("discipline_a_id < discipline_b_id", name="ck_synergy_ordering"),
    )

    def __repr__(self) -> str:
        return f"<DisciplineSynergy {self.discipline_a_id}<->{self.discipline_b_id}>"


class Ability(Base):
    __tablename__ = "abilities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    power_system_id: Mapped[int] = mapped_column(
        ForeignKey("power_systems.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    discipline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("power_disciplines.id", ondelete="SET NULL"), nullable=True,
    )
    minimum_rank_id: Mapped[int] = mapped_column(
        ForeignKey("power_ranks.id", ondelete="CASCADE"),
    )
    energy_cost: Mapped[str] = mapped_column(Text)
    cooldown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    side_effects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prerequisites: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    effects: Mapped[list[Any]] = mapped_column(JSON)
    mastery_levels: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    power_system: Mapped[PowerSystem] = relationship(back_populates="abilities")
    discipline: Mapped[Optional[PowerDiscipline]] = relationship(
        foreign_keys=[discipline_id],
    )
    minimum_rank: Mapped[PowerRank] = relationship(foreign_keys=[minimum_rank_id])

    def __repr__(self) -> str:
        return f"<Ability id={self.id} name={self.name!r}>"


class CharacterPowerProfile(Base):
    __tablename__ = "character_power_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), unique=True,
    )
    current_rank_id: Mapped[int] = mapped_column(
        ForeignKey("power_ranks.id", ondelete="CASCADE"),
    )
    primary_discipline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("power_disciplines.id", ondelete="SET NULL"), nullable=True,
    )
    secondary_discipline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("power_disciplines.id", ondelete="SET NULL"), nullable=True,
    )
    advancement_progress: Mapped[float] = mapped_column(Float, default=0.0)
    energy_capacity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bottleneck_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unique_traits: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    power_philosophy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    character: Mapped[Character] = relationship(back_populates="power_profile")
    current_rank: Mapped[PowerRank] = relationship(foreign_keys=[current_rank_id])
    primary_discipline: Mapped[Optional[PowerDiscipline]] = relationship(
        foreign_keys=[primary_discipline_id],
    )
    secondary_discipline: Mapped[Optional[PowerDiscipline]] = relationship(
        foreign_keys=[secondary_discipline_id],
    )

    def __repr__(self) -> str:
        return f"<CharacterPowerProfile character_id={self.character_id}>"


class CharacterAbility(Base):
    __tablename__ = "character_abilities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    ability_id: Mapped[int] = mapped_column(
        ForeignKey("abilities.id", ondelete="CASCADE"),
    )
    proficiency: Mapped[str] = mapped_column(String(30), default="novice")
    learned_at_chapter: Mapped[int] = mapped_column(Integer)
    learning_method: Mapped[str] = mapped_column(String(100))
    mastery_level: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    character: Mapped[Character] = relationship(back_populates="abilities")
    ability: Mapped[Ability] = relationship()

    __table_args__ = (
        UniqueConstraint("character_id", "ability_id", name="uq_char_ability"),
    )

    def __repr__(self) -> str:
        return f"<CharacterAbility char={self.character_id} ability={self.ability_id}>"


class CharacterPowerSource(Base):
    __tablename__ = "character_power_sources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    source_type: Mapped[str] = mapped_column(String(50))
    source_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    acquired_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    acquisition_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    benefits: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    costs: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    character: Mapped[Character] = relationship(back_populates="power_sources")

    def __repr__(self) -> str:
        return f"<CharacterPowerSource id={self.id} name={self.source_name!r}>"


class AdvancementEvent(Base):
    __tablename__ = "advancement_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    chapter_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    struggle_context: Mapped[str] = mapped_column(Text)
    sacrifice_or_cost: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    foundation: Mapped[str] = mapped_column(Text)
    narrative_buildup_chapters: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    old_rank_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("power_ranks.id", ondelete="SET NULL"), nullable=True,
    )
    new_rank_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("power_ranks.id", ondelete="SET NULL"), nullable=True,
    )
    ability_gained_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("abilities.id", ondelete="SET NULL"), nullable=True,
    )
    earned_power_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    character: Mapped[Character] = relationship(back_populates="advancement_events")
    old_rank: Mapped[Optional[PowerRank]] = relationship(foreign_keys=[old_rank_id])
    new_rank: Mapped[Optional[PowerRank]] = relationship(foreign_keys=[new_rank_id])
    ability_gained: Mapped[Optional[Ability]] = relationship(foreign_keys=[ability_gained_id])

    def __repr__(self) -> str:
        return f"<AdvancementEvent id={self.id} type={self.event_type!r} ch={self.chapter_number}>"


# ═══════════════════════════════════════════════════════════════════════════
# PLANNING (System 10)
# ═══════════════════════════════════════════════════════════════════════════


class ArcPlan(Base):
    __tablename__ = "arc_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    arc_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    planned_chapters: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_chapter_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_chapter_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    author_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    themes: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    key_events: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    character_arcs: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    is_final_arc: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_targets: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    system_revision_count: Mapped[int] = mapped_column(Integer, default=0)
    arc_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    arc_promises_outstanding: Mapped[Optional[list[Any]]] = mapped_column(
        JSON, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="arc_plans")
    chapter_plans: Mapped[list[ChapterPlan]] = relationship(
        back_populates="arc_plan", cascade="all, delete-orphan",
    )
    chapters: Mapped[list[Chapter]] = relationship(back_populates="arc_plan")

    __table_args__ = (
        Index("idx_arc_plans_novel_status", "novel_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<ArcPlan id={self.id} title={self.title!r} status={self.status!r}>"


class ChapterPlan(Base):
    __tablename__ = "chapter_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    arc_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("arc_plans.id", ondelete="CASCADE"), nullable=True,
    )
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    scene_outline: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    target_beats: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    pov_character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True,
    )
    target_tension: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reader_signals: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    chekhov_directives: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    plot_threads_advance: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    plot_threads_rest: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    foreshadowing_directives: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    planned_power_events: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    is_bridge: Mapped[bool] = mapped_column(Boolean, default=False)
    bridge_theme: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    author_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    arc_plan: Mapped[Optional[ArcPlan]] = relationship(back_populates="chapter_plans")
    novel: Mapped[Novel] = relationship(back_populates="chapter_plans")

    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_number", name="uq_chplan_novel_chapter"),
        Index("idx_chapter_plans_arc", "arc_plan_id"),
        CheckConstraint(
            "NOT (is_bridge = TRUE AND arc_plan_id IS NOT NULL)",
            name="ck_bridge_no_arc",
        ),
    )

    def __repr__(self) -> str:
        return f"<ChapterPlan id={self.id} ch={self.chapter_number} bridge={self.is_bridge}>"


class PlotThread(Base):
    __tablename__ = "plot_threads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    thread_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    introduced_at_chapter: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")
    resolution_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolution_conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    related_character_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    related_entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="plot_threads")

    __table_args__ = (
        Index("idx_plot_threads_novel_status", "novel_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<PlotThread id={self.id} name={self.name!r} status={self.status!r}>"


# ═══════════════════════════════════════════════════════════════════════════
# ESCALATION (System 3)
# ═══════════════════════════════════════════════════════════════════════════


class ScopeTier(Base):
    __tablename__ = "scope_tiers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    tier_order: Mapped[int] = mapped_column(Integer)
    tier_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    geography_scale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    power_range: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    antagonist_caliber: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stakes_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_conflicts: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    key_resources: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    revelation_triggers: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    foreshadowing_seeds_json: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    qualitative_difference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="scope_tiers")
    escalation_states: Mapped[list[EscalationState]] = relationship(
        back_populates="scope_tier", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("novel_id", "tier_order", name="uq_scope_novel_tier"),
    )

    def __repr__(self) -> str:
        return f"<ScopeTier id={self.id} name={self.tier_name!r} order={self.tier_order}>"


class EscalationState(Base):
    __tablename__ = "escalation_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    current_tier_id: Mapped[int] = mapped_column(
        ForeignKey("scope_tiers.id", ondelete="CASCADE"),
    )
    current_phase: Mapped[str] = mapped_column(String(30))
    tension_level: Mapped[float] = mapped_column(Float, default=0.0)
    relative_power: Mapped[float] = mapped_column(Float, default=0.0)
    activated_at_chapter: Mapped[int] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="escalation_states")
    scope_tier: Mapped[ScopeTier] = relationship(back_populates="escalation_states")

    def __repr__(self) -> str:
        return f"<EscalationState id={self.id} phase={self.current_phase!r}>"


class ForeshadowingSeed(Base):
    __tablename__ = "foreshadowing_seeds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text)
    planted_at_chapter: Mapped[int] = mapped_column(Integer)
    target_chapter_range: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    seed_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="planted")
    fulfilled_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scope_tier: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="foreshadowing_seeds")

    def __repr__(self) -> str:
        return f"<ForeshadowingSeed id={self.id} type={self.seed_type!r} status={self.status!r}>"


class TensionTracker(Base):
    __tablename__ = "tension_tracker"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_number: Mapped[int] = mapped_column(Integer)
    tension_level: Mapped[float] = mapped_column(Float)
    tension_phase: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    key_tension_drivers: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="tension_trackers")

    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_number", name="uq_tension_novel_chapter"),
    )

    def __repr__(self) -> str:
        return f"<TensionTracker novel={self.novel_id} ch={self.chapter_number}>"


# ═══════════════════════════════════════════════════════════════════════════
# STORY BIBLE & KNOWLEDGE (System 7)
# ═══════════════════════════════════════════════════════════════════════════


class StoryBibleEntry(Base):
    __tablename__ = "story_bible_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    entry_type: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    source_chapter: Mapped[int] = mapped_column(Integer)
    entity_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    tags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    is_superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("story_bible_entries.id", ondelete="SET NULL"), nullable=True,
    )
    is_public_knowledge: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    last_relevant_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scope_tier: Mapped[int] = mapped_column(Integer, default=1)
    embedding_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(
        back_populates="story_bible_entries", foreign_keys=[novel_id],
    )
    superseded_by: Mapped[Optional[StoryBibleEntry]] = relationship(
        remote_side="StoryBibleEntry.id", foreign_keys=[superseded_by_id],
    )
    entity_links: Mapped[list[BibleEntryEntity]] = relationship(
        back_populates="entry", cascade="all, delete-orphan",
    )
    character_knowledge: Mapped[list[CharacterKnowledge]] = relationship(
        back_populates="bible_entry", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<StoryBibleEntry id={self.id} type={self.entry_type!r}>"


class BibleEntryEntity(Base):
    __tablename__ = "bible_entry_entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("story_bible_entries.id", ondelete="CASCADE"),
    )
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    entry: Mapped[StoryBibleEntry] = relationship(back_populates="entity_links")

    __table_args__ = (
        UniqueConstraint(
            "entry_id", "entity_type", "entity_id",
            name="uq_bible_entity_link",
        ),
    )

    def __repr__(self) -> str:
        return f"<BibleEntryEntity entry={self.entry_id} {self.entity_type}={self.entity_id}>"


class ContextRetrievalLog(Base):
    __tablename__ = "context_retrieval_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_number: Mapped[int] = mapped_column(Integer)
    query_text: Mapped[str] = mapped_column(Text)
    retrieved_entry_ids: Mapped[list[Any]] = mapped_column(JSON)
    relevance_scores: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    total_token_estimate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="context_retrieval_logs")

    def __repr__(self) -> str:
        return f"<ContextRetrievalLog novel={self.novel_id} ch={self.chapter_number}>"


class CharacterKnowledge(Base):
    __tablename__ = "character_knowledge"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    bible_entry_id: Mapped[int] = mapped_column(
        ForeignKey("story_bible_entries.id", ondelete="CASCADE"),
    )
    knows: Mapped[bool] = mapped_column(Boolean, default=True)
    knowledge_level: Mapped[str] = mapped_column(String(20), default="full")
    misconception: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    learned_at_chapter: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    character: Mapped[Character] = relationship(back_populates="knowledge")
    bible_entry: Mapped[StoryBibleEntry] = relationship(back_populates="character_knowledge")

    __table_args__ = (
        UniqueConstraint("character_id", "bible_entry_id", name="uq_char_knowledge"),
        Index("idx_char_knowledge_character", "character_id"),
        Index("idx_char_knowledge_entry", "bible_entry_id"),
    )

    def __repr__(self) -> str:
        return f"<CharacterKnowledge char={self.character_id} entry={self.bible_entry_id}>"


# ═══════════════════════════════════════════════════════════════════════════
# PERSPECTIVE (System 8)
# ═══════════════════════════════════════════════════════════════════════════


class CharacterWorldview(Base):
    __tablename__ = "character_worldviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), unique=True,
    )
    core_beliefs: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    biases: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    blind_spots: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    misconceptions: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    emotional_baseline: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    trust_disposition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    knowledge_boundaries: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    character: Mapped[Character] = relationship(back_populates="worldview")

    def __repr__(self) -> str:
        return f"<CharacterWorldview character_id={self.character_id}>"


class NarrativeVoice(Base):
    __tablename__ = "narrative_voices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), unique=True,
    )
    vocabulary_level: Mapped[str] = mapped_column(String(30), default="educated")
    speech_patterns: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    internal_monologue_style: Mapped[str] = mapped_column(String(30), default="moderate")
    metaphor_preferences: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    emotional_expression_style: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sentence_style: Mapped[str] = mapped_column(String(30), default="flowing")
    humor_style: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    sample_passage: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_evolution: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)

    character: Mapped[Character] = relationship(back_populates="narrative_voice")

    def __repr__(self) -> str:
        return f"<NarrativeVoice character_id={self.character_id}>"


class ChapterPOV(Base):
    __tablename__ = "chapter_pov"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), unique=True,
    )
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    pov_type: Mapped[str] = mapped_column(String(30), default="limited_third")
    worldview_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    voice_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    knowledge_state_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    chapter: Mapped[Chapter] = relationship(back_populates="chapter_pov")
    character: Mapped[Character] = relationship()

    def __repr__(self) -> str:
        return f"<ChapterPOV chapter_id={self.chapter_id} char_id={self.character_id}>"


class PerspectiveDivergence(Base):
    __tablename__ = "perspective_divergences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    character_a_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    character_b_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"),
    )
    topic: Mapped[str] = mapped_column(Text)
    character_a_belief: Mapped[str] = mapped_column(Text)
    character_b_belief: Mapped[str] = mapped_column(Text)
    ground_truth: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    established_at_chapter: Mapped[int] = mapped_column(Integer)
    resolved_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reader_has_full_picture: Mapped[bool] = mapped_column(Boolean, default=False)

    novel: Mapped[Novel] = relationship(back_populates="perspective_divergences")
    character_a: Mapped[Character] = relationship(foreign_keys=[character_a_id])
    character_b: Mapped[Character] = relationship(foreign_keys=[character_b_id])

    def __repr__(self) -> str:
        return (
            f"<PerspectiveDivergence {self.character_a_id} vs "
            f"{self.character_b_id} re: {self.topic[:30]!r}>"
        )


# ═══════════════════════════════════════════════════════════════════════════
# CHEKHOV SYSTEM
# ═══════════════════════════════════════════════════════════════════════════


class ChekhovGun(Base):
    __tablename__ = "chekhov_guns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text)
    introduced_at_chapter: Mapped[int] = mapped_column(Integer)
    gun_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="loaded")
    pressure_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_touched_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolution_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolution_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subversion_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chapters_since_touch: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    bible_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("story_bible_entries.id", ondelete="SET NULL"), nullable=True,
    )
    expected_resolution_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="chekhov_guns")

    __table_args__ = (
        Index("idx_chekhov_novel_status", "novel_id", "status"),
        Index("idx_chekhov_pressure", "novel_id", "pressure_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChekhovGun id={self.id} type={self.gun_type!r} "
            f"status={self.status!r} pressure={self.pressure_score:.2f}>"
        )


# ═══════════════════════════════════════════════════════════════════════════
# VISUAL ASSETS (System 5)
# ═══════════════════════════════════════════════════════════════════════════


class ArtAsset(Base):
    __tablename__ = "art_assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    prompt_used: Mapped[str] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("art_assets.id", ondelete="SET NULL"), nullable=True,
    )
    seed_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    generation_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chapter_context: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    style_tags: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, name="metadata",
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="art_assets")

    def __repr__(self) -> str:
        return f"<ArtAsset id={self.id} type={self.asset_type!r} v={self.version}>"


class ArtStyleGuide(Base):
    __tablename__ = "art_style_guides"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    style_description: Mapped[str] = mapped_column(Text)
    style_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    color_palette: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    art_direction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_prompt_prefix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_negative_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference_asset_ids: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    model_preference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    default_params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="art_style_guides")

    __table_args__ = (
        UniqueConstraint("novel_id", "style_name", name="uq_style_guide_novel_name"),
    )

    def __repr__(self) -> str:
        return f"<ArtStyleGuide id={self.id} novel_id={self.novel_id}>"


class ArtGenerationQueue(Base):
    __tablename__ = "art_generation_queue"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_event: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    trigger_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("art_assets.id", ondelete="SET NULL"), nullable=True,
    )
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="art_generation_queue")

    def __repr__(self) -> str:
        return f"<ArtGenerationQueue id={self.id} type={self.asset_type!r} status={self.status!r}>"


# ═══════════════════════════════════════════════════════════════════════════
# READER INFLUENCE (System 6)
# ═══════════════════════════════════════════════════════════════════════════


class ReaderSignal(Base):
    __tablename__ = "reader_signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    reader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    chapter_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    signal_type: Mapped[str] = mapped_column(String(50))
    intensity: Mapped[int] = mapped_column(Integer, default=3)
    target_entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    signal_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="reader_signals")
    reader: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return f"<ReaderSignal id={self.id} type={self.signal_type!r}>"


class OracleQuestion(Base):
    __tablename__ = "oracle_questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    reader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_text: Mapped[str] = mapped_column(Text)
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    answer_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    asked_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    votes: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revelation_target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    revelation_target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revelation_planned_chapters: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="oracle_questions")
    reader: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return f"<OracleQuestion id={self.id} status={self.status!r}>"


class ButterflyChoice(Base):
    __tablename__ = "butterfly_choices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_number: Mapped[int] = mapped_column(Integer)
    choice_text_a: Mapped[str] = mapped_column(Text)
    choice_text_b: Mapped[str] = mapped_column(Text)
    choice_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    option_a_theme: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    option_b_theme: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    vote_count_a: Mapped[int] = mapped_column(Integer, default=0)
    vote_count_b: Mapped[int] = mapped_column(Integer, default=0)
    narrative_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    personality_modifier: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    closes_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    voting_closes_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    novel: Mapped[Novel] = relationship(back_populates="butterfly_choices")

    def __repr__(self) -> str:
        return f"<ButterflyChoice id={self.id} ch={self.chapter_number} result={self.result!r}>"


class FactionAlignment(Base):
    __tablename__ = "faction_alignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    faction_id: Mapped[int] = mapped_column(ForeignKey("factions.id", ondelete="CASCADE"))
    alignment_score: Mapped[float] = mapped_column(Float, default=0.5)
    scope_tier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scope_tiers.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    reader: Mapped[User] = relationship()
    novel: Mapped[Novel] = relationship(back_populates="faction_alignments")
    faction: Mapped[Faction] = relationship(back_populates="faction_alignments")

    __table_args__ = (
        UniqueConstraint(
            "reader_id", "novel_id", "faction_id",
            name="uq_faction_alignment",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FactionAlignment reader={self.reader_id} "
            f"faction={self.faction_id} score={self.alignment_score}>"
        )


# ═══════════════════════════════════════════════════════════════════════════
# COST TRACKING
# ═══════════════════════════════════════════════════════════════════════════


class LLMUsageLog(Base):
    __tablename__ = "llm_usage_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=True,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[float] = mapped_column(Float)
    purpose: Mapped[str] = mapped_column(String(50))
    chapter_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Optional[Novel]] = relationship(back_populates="llm_usage_logs")
    user: Mapped[User] = relationship(back_populates="llm_usage_logs")

    __table_args__ = (
        Index("idx_llm_usage_novel", "novel_id"),
        Index("idx_llm_usage_user", "user_id"),
        Index("idx_llm_usage_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LLMUsageLog id={self.id} model={self.model!r} cost={self.cost_cents:.2f}>"


class ImageUsageLog(Base):
    __tablename__ = "image_usage_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dimensions: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cost_cents: Mapped[float] = mapped_column(Float)
    purpose: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    art_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("art_assets.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="image_usage_logs")

    def __repr__(self) -> str:
        return f"<ImageUsageLog id={self.id} provider={self.provider!r}>"


# ═══════════════════════════════════════════════════════════════════════════
# WORKER & JOBS
# ═══════════════════════════════════════════════════════════════════════════


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(50))
    arq_job_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True)
    chapter_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stage_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partial_data_cleaned: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True, name="metadata",
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="generation_jobs")

    __table_args__ = (
        Index("idx_generation_jobs_novel", "novel_id"),
        Index("idx_generation_jobs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<GenerationJob id={self.id} type={self.job_type!r} status={self.status!r}>"


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    novel_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=True,
    )
    notification_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    action_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delivery_channel: Mapped[str] = mapped_column(String(20), default="in_app")
    related_entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    user: Mapped[User] = relationship(back_populates="notifications")
    novel: Mapped[Optional[Novel]] = relationship(back_populates="notifications")

    __table_args__ = (
        Index("idx_notifications_user_unread", "user_id", "is_read", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Notification id={self.id} type={self.notification_type!r} read={self.is_read}>"


# ═══════════════════════════════════════════════════════════════════════════
# DISCOVERY
# ═══════════════════════════════════════════════════════════════════════════


class NovelStats(Base):
    __tablename__ = "novel_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), unique=True,
    )
    total_chapters: Mapped[int] = mapped_column(Integer, default=0)
    total_words: Mapped[int] = mapped_column(Integer, default=0)
    total_readers: Mapped[int] = mapped_column(Integer, default=0)
    avg_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    last_chapter_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="novel_stats")

    def __repr__(self) -> str:
        return f"<NovelStats novel_id={self.novel_id} chapters={self.total_chapters}>"


class NovelRating(Base):
    __tablename__ = "novel_ratings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    reader_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(Integer)
    review_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    novel: Mapped[Novel] = relationship(back_populates="novel_ratings")
    reader: Mapped[User] = relationship()

    __table_args__ = (
        UniqueConstraint("novel_id", "reader_id", name="uq_novel_rating"),
    )

    def __repr__(self) -> str:
        return f"<NovelRating novel={self.novel_id} reader={self.reader_id} rating={self.rating}>"


class NovelTag(Base):
    __tablename__ = "novel_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    tag_name: Mapped[str] = mapped_column(String(100))
    tag_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_system_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="novel_tags")

    __table_args__ = (
        UniqueConstraint("novel_id", "tag_name", name="uq_novel_tag"),
    )

    def __repr__(self) -> str:
        return f"<NovelTag novel={self.novel_id} tag={self.tag_name!r}>"


class NovelSeed(Base):
    __tablename__ = "novel_seeds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    seed_id: Mapped[str] = mapped_column(String(100))
    seed_category: Mapped[str] = mapped_column(String(50))
    seed_text: Mapped[str] = mapped_column(Text)
    # proposed|confirmed|rejected
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="novel_seeds")

    __table_args__ = (
        UniqueConstraint("novel_id", "seed_id", name="uq_novel_seed"),
    )

    def __repr__(self) -> str:
        return f"<NovelSeed novel={self.novel_id} seed={self.seed_id!r} status={self.status!r}>"


# ═══════════════════════════════════════════════════════════════════════════
# BYOK API KEY MANAGEMENT (Multi-Tenant)
# ═══════════════════════════════════════════════════════════════════════════


class AuthorAPIKey(Base):
    """Encrypted API keys provided by BYOK authors."""

    __tablename__ = "author_api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))  # anthropic, openai, replicate
    encrypted_key: Mapped[str] = mapped_column(Text)  # Fernet ciphertext
    key_suffix: Mapped[str] = mapped_column(String(10))  # last 4 chars for display
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    validated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="api_keys")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_author_api_key_provider"),
    )

    def __repr__(self) -> str:
        return f"<AuthorAPIKey user={self.user_id} provider={self.provider!r}>"


class APIKeyAuditLog(Base):
    """Audit trail for API key operations."""

    __tablename__ = "api_key_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(20))  # added, removed, validated, failed
    provider: Mapped[str] = mapped_column(String(50))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    __table_args__ = (
        Index("idx_audit_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<APIKeyAuditLog user={self.user_id} action={self.action!r}>"
