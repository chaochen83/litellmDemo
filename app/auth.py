"""
API Key 鉴权 + Redis QPS 限流
"""
import hashlib
import time
from typing import Optional

from fastapi import HTTPException, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, AsyncSessionLocal
from app.models import ApiKey

# Redis 客户端（懒加载，无 Redis 时限流跳过）
_redis = None


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    try:
        from redis.asyncio import Redis
        url = get_settings().redis_url
        if not url:
            return None
        _redis = Redis.from_url(url, decode_responses=True)
        return _redis
    except Exception:
        return None


def hash_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def key_prefix(plain: str) -> str:
    if len(plain) <= 8:
        return plain
    return plain[:4] + "..." + plain[-4:]


async def get_api_key_from_db(key_hash: str, db: AsyncSession) -> Optional[ApiKey]:
    r = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash).limit(1))
    return r.scalar_one_or_none()


async def get_current_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization: Bearer <key>")
    plain = auth[7:].strip()
    if not plain:
        raise HTTPException(status_code=401, detail="Empty API key")
    kh = hash_key(plain)
    key_record = await get_api_key_from_db(kh, db)
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key_record


async def check_rate_limit(api_key: ApiKey) -> None:
    """Redis QPS 限流：超过 rate_limit_qps 则 429。无 Redis 时不限流。"""
    if api_key.rate_limit_qps <= 0:
        return
    redis_client = _get_redis()
    if redis_client is None:
        return
    window = int(time.time())
    rkey = f"rl:{api_key.id}:{window}"
    try:
        n = await redis_client.incr(rkey)
        if n == 1:
            await redis_client.expire(rkey, 2)
        if n > api_key.rate_limit_qps:
            from app.metrics import RATE_LIMIT_HITS
            RATE_LIMIT_HITS.labels(user_id=api_key.user_id).inc()
            raise HTTPException(status_code=429, detail="Rate limit exceeded (QPS)")
    except HTTPException:
        raise
    except Exception:
        pass  # Redis 不可用时放行
