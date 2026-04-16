from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Boolean, Text, ForeignKey, DateTime
from datetime import datetime, timezone
from config import settings


engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft | rendering | complete | error
    final_video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    clips: Mapped[list["Clip"]] = relationship(
        "Clip", back_populates="project", cascade="all, delete-orphan", order_by="Clip.order"
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(255), default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    end_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str] = mapped_column(String(10), default="720p")
    duration: Mapped[str] = mapped_column(String(10), default="auto")
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="auto")
    generate_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Generation state
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending | queued | generating | complete | error
    fal_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship("Project", back_populates="clips")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
