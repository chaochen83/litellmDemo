from datetime import datetime
from sqlalchemy import String, DateTime, Integer, Float, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ApiKey(Base):
    """API Key 系统：虚拟 key，用于鉴权与限流"""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256(plain_key)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)  # 显示用，如 sk-xxx 前几位
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    rate_limit_qps: Mapped[int] = mapped_column(Integer, default=10)  # 每秒最多请求数，0=不限
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SecurityLog(Base):
    __tablename__ = "security_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(32), index=True)  # risk | desensitize
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
