"""Pydantic v2 schemas for API serialization.

Every model that appears in an API response gets a schema here.
All schemas use ``model_config = ConfigDict(from_attributes=True)``
so they can be created directly from SQLAlchemy ORM objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ═══════════════════════════════════════════════════════════════════════════
# Users & Auth
# ═══════════════════════════════════════════════════════════════════════════


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime


class AuthorProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    display_name: Optional[str] = None
    bio: Optional[str] = None
    payment_status: str
    api_budget_cents: int
    api_spent_cents: int
    image_budget_cents: int
    image_spent_cents: int
    plan_type: str
    created_at: datetime


class ReaderBookmarkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    novel_id: int
    last_chapter_read: int
    notify_on_update: bool
    created_at: datetime
    updated_at: datetime


class ReaderBookmarkCreate(BaseModel):
    novel_id: int
    last_chapter_read: int = 0
    notify_on_update: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Novel
# ═══════════════════════════════════════════════════════════════════════════


class NovelCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    genre: str = "progression_fantasy"
    tags: list[str] = Field(default_factory=list, max_length=15)
    custom_genre_conventions: str | None = None


class NovelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    title: str
    genre: str
    status: str
    autonomous_enabled: bool
    is_public: bool
    share_token: Optional[str] = None
    completion_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class NovelList(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    genre: str
    status: str
    is_public: bool
    created_at: datetime


class NovelSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    novel_id: int
    planning_mode: str
    pov_mode: str
    content_rating: str
    target_chapter_length: int
    default_temperature: float
    reader_influence_enabled: bool
    image_generation_enabled: bool
    autonomous_generation_enabled: bool
    autonomous_cadence_hours: int
    autonomous_skip_arc_boundaries: bool
    autonomous_daily_budget_cents: int


# ═══════════════════════════════════════════════════════════════════════════
# Chapter
# ═══════════════════════════════════════════════════════════════════════════


class ChapterCreate(BaseModel):
    title: Optional[str] = None
    chapter_text: str
    chapter_number: Optional[int] = None


class ChapterImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paragraph_index: int
    scene_description: str
    image_url: Optional[str] = None
    status: str


class ChapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    chapter_number: int
    title: Optional[str] = None
    chapter_text: str
    word_count: Optional[int] = None
    pov_character_id: Optional[int] = None
    model_used: Optional[str] = None
    status: str
    is_bridge: bool
    images: list[ChapterImageRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChapterList(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    chapter_number: int
    title: Optional[str] = None
    word_count: Optional[int] = None
    status: str
    is_bridge: bool
    created_at: datetime


class ChapterSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_id: int
    summary_type: str
    content: str
    key_events: Optional[list[Any]] = None
    emotional_arc: Optional[str] = None
    cliffhangers: Optional[list[Any]] = None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Character
# ═══════════════════════════════════════════════════════════════════════════


class CharacterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    name: str
    role: str
    description: str
    visual_appearance: Optional[str] = None
    personality_traits: Optional[list[Any]] = None
    background: Optional[str] = None
    motivation: Optional[str] = None
    current_goal: Optional[str] = None
    scope_tier: int
    introduced_at_chapter: Optional[int] = None
    is_alive: bool
    arc_summary: Optional[str] = None


class CharacterList(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: str
    is_alive: bool
    scope_tier: int
    introduced_at_chapter: Optional[int] = None


class CharacterPowerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    character_id: int
    current_rank_id: int
    primary_discipline_id: Optional[int] = None
    secondary_discipline_id: Optional[int] = None
    advancement_progress: float
    energy_capacity: Optional[str] = None
    bottleneck_description: Optional[str] = None
    unique_traits: Optional[list[Any]] = None
    power_philosophy: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# Planning
# ═══════════════════════════════════════════════════════════════════════════


class ArcPlanCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str
    planned_chapters: Optional[int] = None
    themes: Optional[list[Any]] = None
    key_events: Optional[list[Any]] = None
    character_arcs: Optional[list[Any]] = None
    is_final_arc: bool = False


class ArcPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    arc_number: Optional[int] = None
    title: str
    description: str
    planned_chapters: Optional[int] = None
    target_chapter_start: Optional[int] = None
    target_chapter_end: Optional[int] = None
    status: str
    author_notes: Optional[str] = None
    themes: Optional[list[Any]] = None
    key_events: Optional[list[Any]] = None
    character_arcs: Optional[list[Any]] = None
    is_final_arc: bool
    resolution_targets: Optional[list[Any]] = None
    created_at: datetime
    updated_at: datetime


class PlotThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    name: str
    description: str
    thread_type: Optional[str] = None
    status: str
    introduced_at_chapter: int
    resolution_chapter: Optional[int] = None
    priority: int


# ═══════════════════════════════════════════════════════════════════════════
# Chekhov
# ═══════════════════════════════════════════════════════════════════════════


class ChekhovGunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    description: str
    introduced_at_chapter: int
    gun_type: str
    status: str
    pressure_score: float
    last_touched_chapter: Optional[int] = None
    resolution_chapter: Optional[int] = None
    resolution_description: Optional[str] = None
    chapters_since_touch: int
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Power System
# ═══════════════════════════════════════════════════════════════════════════


class PowerSystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    system_name: str
    core_mechanic: str
    energy_source: str
    power_ceiling: str


class PowerRankRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rank_name: str
    rank_order: int
    description: str
    typical_capabilities: str
    scope_tier: int


# ═══════════════════════════════════════════════════════════════════════════
# Notifications
# ═══════════════════════════════════════════════════════════════════════════


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    novel_id: Optional[int] = None
    notification_type: str
    title: str
    message: str
    action_url: Optional[str] = None
    is_read: bool
    delivery_channel: str
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Discovery
# ═══════════════════════════════════════════════════════════════════════════


class NovelStatsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    total_chapters: int
    total_words: int
    total_readers: int
    avg_rating: Optional[float] = None
    rating_count: int
    last_chapter_at: Optional[datetime] = None
    updated_at: datetime


class NovelRatingCreate(BaseModel):
    novel_id: int
    rating: int = Field(..., ge=-5, le=5)
    review_text: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_not_zero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Rating cannot be zero")
        return v


class NovelRatingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    reader_id: int
    rating: int
    review_text: Optional[str] = None
    created_at: datetime


class NovelTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    tag_name: str
    tag_category: str | None = None
    is_system_generated: bool


class NovelSeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    seed_id: str
    seed_category: str
    seed_text: str
    status: str
    created_at: datetime


class TagInfo(BaseModel):
    name: str
    slug: str
    category: str
    description: str


class TagCatalogResponse(BaseModel):
    categories: dict[str, list[TagInfo]]


# ═══════════════════════════════════════════════════════════════════════════
# Worker & Jobs
# ═══════════════════════════════════════════════════════════════════════════


class GenerationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    job_type: str
    arq_job_id: Optional[str] = None
    chapter_number: Optional[int] = None
    status: str
    attempt_number: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Cost Tracking
# ═══════════════════════════════════════════════════════════════════════════


class LLMUsageLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: Optional[int] = None
    user_id: int
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_cents: float
    purpose: str
    chapter_number: Optional[int] = None
    duration_ms: Optional[int] = None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Art Assets
# ═══════════════════════════════════════════════════════════════════════════


class ArtAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    asset_type: str
    entity_id: Optional[int] = None
    entity_type: Optional[str] = None
    image_url: Optional[str] = None
    file_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    provider: Optional[str] = None
    model_used: Optional[str] = None
    version: int = 1
    is_current: bool = True
    parent_asset_id: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    description: Optional[str] = None
    chapter_context: Optional[int] = None
    style_tags: Optional[list[Any]] = None
    created_at: datetime


# ═══════════════════════════════════════════════════════════════════════════
# Pagination wrapper
# ═══════════════════════════════════════════════════════════════════════════


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list[Any]
    page: int
    page_size: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size
