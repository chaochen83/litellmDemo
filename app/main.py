import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import litellm
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, engine, AsyncSessionLocal, Base
from app.models import RequestLog, SecurityLog, ApiKey
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY, TOKEN_TOTAL, REQUEST_ACTIVE, get_metrics
from app.router_logic import RoutingGoal, get_routing_goal, set_routing_goal, get_models_for_goal
from app.auth import get_current_key, check_rate_limit, hash_key, key_prefix

# 确保环境变量传入 LiteLLM
_settings = get_settings()
if _settings.openai_api_key:
    os.environ.setdefault("OPENAI_API_KEY", _settings.openai_api_key)
if _settings.anthropic_api_key:
    os.environ.setdefault("ANTHROPIC_API_KEY", _settings.anthropic_api_key)
if _settings.dashscope_api_key:
    os.environ.setdefault("DASHSCOPE_API_KEY", _settings.dashscope_api_key)


async def _seed_security_logs():
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select, func
        r = await db.execute(select(func.count(SecurityLog.id)))
        if (r.scalar() or 0) > 0:
            return
        for level, title, content in [
            ("risk", "风险拦截", "检测到prompt包含企业级机密代码片段"),
            ("desensitize", "脱敏处理", "自动屏蔽手机号以及身份证信息"),
        ]:
            db.add(SecurityLog(level=level, title=title, content=content))
        await db.commit()


async def _seed_api_keys():
    """默认 API Key，便于本地测试。生产应从管理端创建。"""
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select, func
        r = await db.execute(select(func.count(ApiKey.id)))
        if (r.scalar() or 0) > 0:
            return
        default_plain = "sk-demo-12345678"
        db.add(ApiKey(
            name="默认 Key",
            key_hash=hash_key(default_plain),
            key_prefix=key_prefix(default_plain),
            user_id="default",
            rate_limit_qps=10,
        ))
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_security_logs()
    await _seed_api_keys()
    yield
    await engine.dispose()


app = FastAPI(title="LiteLLM Router Gateway", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 静态与前端
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- 对话接口 ----------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str | None = None  # 可选：不传则按当前 Router 策略选模型
    messages: list[ChatMessage]
    stream: bool = False


@app.post("/v1/chat/completions")
async def chat_completions(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key: ApiKey = Depends(get_current_key),
):
    user_id = api_key.user_id
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    await check_rate_limit(api_key)

    # 按当前选路策略取模型列表，支持 provider fallback
    goal = get_routing_goal()
    model_list = get_models_for_goal(goal)
    primary_model = (req.model or "").strip() or model_list[0]
    fallbacks = [m for m in model_list if m != primary_model]

    start = time.perf_counter()
    REQUEST_ACTIVE.labels(model=primary_model).inc()
    try:
        response = await litellm.acompletion(
            model=primary_model,
            messages=messages,
            stream=False,
            fallbacks=fallbacks if fallbacks else None,
        )
        print(response)
        latency_ms = (time.perf_counter() - start) * 1000
        usage = getattr(response, "usage", None) or {}
        input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0)
        # 实际命中的模型（可能 fallback 到别的）
        model_used = getattr(response, "model", None) or primary_model
        REQUEST_COUNT.labels(model=model_used, user_id=user_id).inc()
        REQUEST_LATENCY.labels(model=model_used).observe(latency_ms / 1000.0)
        TOKEN_TOTAL.labels(model=model_used, user_id=user_id).inc(int(input_tokens) + int(output_tokens))
        log = RequestLog(
            model=model_used,
            user_id=user_id,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            latency_ms=latency_ms,
        )
        db.add(log)
        REQUEST_ACTIVE.labels(model=primary_model).dec()
        return litellm_response_to_dict(response)
    except Exception as e:
        REQUEST_ACTIVE.labels(model=primary_model).dec()
        raise HTTPException(status_code=500, detail=str(e))


def litellm_response_to_dict(response):
    try:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "choices"):
            u = getattr(response, "usage", None)
            usage = u.model_dump() if u and hasattr(u, "model_dump") else (u or {})
            choices = [c.model_dump() if hasattr(c, "model_dump") else c for c in response.choices]
            return {"choices": choices, "usage": usage}
        return {"choices": [], "usage": {}}
    except Exception:
        return {"choices": [], "usage": {}}


# ---------- Prometheus ----------
@app.get("/metrics")
async def metrics():
    return Response(content=get_metrics(), media_type="text/plain")


# ---------- 数据看板 API ----------
@app.get("/api/dashboard/summary")
async def dashboard_summary(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = (today_start.replace(day=1))

    # 实时请求峰值 QPS：最近 1 分钟请求数 / 60，向上取整为整数 QPS，便于阅读
    r = await db.execute(
        select(func.count(RequestLog.id)).where(
            RequestLog.created_at >= now - timedelta(minutes=1)
        )
    )
    count_1m = r.scalar() or 0
    if count_1m == 0:
        peak_qps = 0
    else:
        window = 60
        peak_qps = int((count_1m + window - 1) / window)

    # 今日消耗 token
    r = await db.execute(
        select(func.coalesce(func.sum(RequestLog.input_tokens + RequestLog.output_tokens), 0)).where(
            RequestLog.created_at >= today_start
        )
    )
    today_tokens = r.scalar() or 0
    today_tokens_val = float(today_tokens or 0)
    if today_tokens_val >= 1_000_000:
        today_tokens_str = f"{today_tokens_val / 1e6:.1f} M"
    elif today_tokens_val >= 1_000:
        today_tokens_str = f"{today_tokens_val / 1e3:.1f} K"
    else:
        today_tokens_str = str(int(today_tokens_val))

    # 平均响应延迟（今日）
    r = await db.execute(
        select(func.avg(RequestLog.latency_ms)).where(
            RequestLog.created_at >= today_start,
            RequestLog.latency_ms.isnot(None),
        )
    )
    avg_latency_ms = r.scalar() or 0
    avg_latency_str = f"{avg_latency_ms / 1000:.1f}s"

    # 本月估算支出（示例：按 token 粗算，可换成真实 cost 字段）
    r = await db.execute(
        select(func.coalesce(func.sum(RequestLog.input_tokens + RequestLog.output_tokens), 0)).where(
            RequestLog.created_at >= month_start
        )
    )
    month_tokens = r.scalar() or 0
    month_tokens_val = float(month_tokens or 0)
    # 粗略 1M token ≈ 2 美元 ≈ 14 元
    month_cny = (month_tokens_val / 1e6) * 2 * 7
    month_cny_str = f"￥{month_cny:,.0f}"

    return {
        "peak_qps": peak_qps,
        "peak_qps_display": f"{peak_qps} QPS",
        "today_tokens": today_tokens,
        "today_tokens_display": today_tokens_str,
        "avg_latency_display": avg_latency_str,
        "month_spend_display": month_cny_str,
    }


@app.get("/api/dashboard/qps_by_model")
async def qps_by_model(
    range_hours: int = 24,
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=range_hours)
    # 按 5 分钟桶 + 模型聚合（MySQL）
    r = await db.execute(
        text("""
        SELECT
            model,
            FLOOR(UNIX_TIMESTAMP(created_at) / 300) * 300 AS bucket_ts,
            COUNT(*) AS cnt
        FROM request_logs
        WHERE created_at >= :since
        GROUP BY model, bucket_ts
        ORDER BY bucket_ts, model
        """),
        {"since": since},
    )
    rows = r.mappings().all()
    # 按模型分组为时间序列
    by_model = {}
    for row in rows:
        m = row["model"]
        if m not in by_model:
            by_model[m] = []
        by_model[m].append({"time": row["bucket_ts"], "qps": round(row["cnt"] / 300.0, 2)})
    return {"range_hours": range_hours, "series": by_model}


@app.get("/api/dashboard/security_logs")
async def security_logs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(SecurityLog).order_by(SecurityLog.created_at.desc()).limit(limit)
    )
    logs = r.scalars().all()
    return [
        {
            "id": l.id,
            "level": l.level,
            "title": l.title,
            "content": l.content,
            "time": l.created_at.strftime("%H:%M:%S") if l.created_at else "",
        }
        for l in logs
    ]


# ---------- 选路策略 ----------
@app.get("/api/routing/goal")
async def get_goal():
    return {"goal": get_routing_goal().value}


class SetGoalBody(BaseModel):
    goal: str  # 成本优先 | 响应延迟优先 | 最大精度优先 | 合规隔离优先


@app.post("/api/routing/goal")
async def post_goal(body: SetGoalBody):
    m = {g.value: g for g in RoutingGoal}
    if body.goal not in m:
        raise HTTPException(400, f"unknown goal: {body.goal}")
    set_routing_goal(m[body.goal])
    return {"goal": body.goal}


# ---------- API Key 管理（可选：生产建议加 ADMIN_SECRET 鉴权）---------
def _generate_plain_key() -> str:
    import secrets
    return "sk-" + secrets.token_hex(16)


class CreateKeyBody(BaseModel):
    name: str = ""
    user_id: str = "default"
    rate_limit_qps: int = 10


@app.post("/api/keys")
async def create_key(body: CreateKeyBody, db: AsyncSession = Depends(get_db)):
    plain = _generate_plain_key()
    db.add(ApiKey(
        name=body.name or "API Key",
        key_hash=hash_key(plain),
        key_prefix=key_prefix(plain),
        user_id=body.user_id,
        rate_limit_qps=max(0, body.rate_limit_qps),
    ))
    return {"key": plain, "key_prefix": key_prefix(plain), "user_id": body.user_id}


# ---------- 前端页面 ----------
def _load_html(name: str) -> str:
    path = os.path.join(STATIC_DIR, name)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<!DOCTYPE html><html><body>Page not found.</body></html>"


@app.get("/", response_class=HTMLResponse)
async def index():
    return _load_html("index.html")


@app.get("/routing", response_class=HTMLResponse)
async def routing_page():
    return _load_html("routing.html")


