"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) của toàn agent vào Redis, key theo ngày UTC
    → sang ngày mới là key mới = tự reset, không cần cron
  • Tổng chi phí (cộng cả ước tính của request sắp gọi) vượt DAILY_BUDGET_USD → HTTP 402
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
KEY_TTL_SECONDS = 2 * 24 * 3600


def _key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def estimate_tokens(text: str) -> int:
    # shortcut: ~4 ký tự / token; thay bằng tokenizer của model khi dùng LLM thật
    return max(1, len(text) // 4)


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K


def check_budget(estimated_usd: float = 0.0) -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = float(r.get(_key()) or 0)
    budget = settings.daily_budget_usd
    if spent + estimated_usd > budget:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "spent_usd": round(spent, 6),
                    "budget_usd": budget, "resets_at": "00:00 UTC"},
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng (INCRBYFLOAT là atomic), trả về chi phí request."""
    cost = cost_usd(input_tokens, output_tokens)
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(_key(), cost)
    pipe.expire(_key(), KEY_TTL_SECONDS)
    pipe.execute()
    return cost
