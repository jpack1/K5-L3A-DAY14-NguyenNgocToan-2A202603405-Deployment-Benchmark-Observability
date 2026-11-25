"""
Production AI Agent — Part 6 Final Project.

Chạy:  uvicorn app.main:app --workers 2
Kiểm:  python check_production_ready.py
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, cost_usd, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng log của app là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)  # json.dumps escape \n → vẫn 1 dòng
        return json.dumps(entry, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


def log(event: str, level: int = logging.INFO, **fields):
    logger.log(level, event, extra={"fields": fields})


START_TIME = time.time()
_shutting_down = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _shutting_down
    log("startup", environment=settings.environment, port=settings.port,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd, redis_ok=redis_healthy())
    yield
    # Graceful shutdown: uvicorn đã ngừng nhận kết nối mới và chờ request đang chạy xong
    # rồi mới chạy tới đây → chỉ còn dọn dẹp tài nguyên.
    _shutting_down = True
    r.close()
    log("shutdown_complete", uptime_seconds=round(time.time() - START_TIME, 1))


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log("request", method=request.method, path=request.url.path, status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 1))
    return response


@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    log("dependency_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Dependency unavailable, try again later"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # Không trả stack trace cho client; chi tiết chỉ nằm trong log
    log("unhandled_error", logging.ERROR, path=request.url.path, error=repr(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness: process còn chạy là 200, không phụ thuộc Redis."""
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1),
            "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 503 khi Redis không kết nối được hoặc đang tắt → load balancer ngừng gửi traffic."""
    if _shutting_down or not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "redis": "unavailable"})
    return {"ready": True, "redis": "ok"}


# `def` (không async): FastAPI chạy trong threadpool nên lời gọi LLM blocking không chặn event loop
# — /health vẫn trả lời được, và SIGTERM không cắt các request đang xếp hàng.
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    input_tokens = estimate_tokens(body.question)
    check_budget(cost_usd(input_tokens, 0))

    answer = llm_ask(body.question)

    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    log("llm_call", input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 8))
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }
