from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def now(): return datetime.now(timezone.utc)

class Article(Base):
    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(1000))
    body: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(255), index=True)
    section: Mapped[str] = mapped_column(String(100), default="nao_identificada", index=True)
    journalist: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    journalist_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    classification: Mapped["Classification"] = relationship(back_populates="article", cascade="all, delete-orphan", uselist=False)

class Classification(Base):
    __tablename__ = "classifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), unique=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    tone: Mapped[str] = mapped_column(String(30), default="neutro", index=True)
    impact_score: Mapped[float] = mapped_column(Float, default=0)
    matched_keywords: Mapped[str] = mapped_column(Text, default="[]")
    evidence: Mapped[str] = mapped_column(Text, default="[]")
    article: Mapped[Article] = relationship(back_populates="classification")
