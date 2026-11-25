"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • redis.from_url chỉ tạo connection pool, chưa kết nối → app khởi động được khi Redis chưa sẵn sàng
  • Timeout ngắn để /ready và /ask không treo khi Redis chết
  • redis_healthy() dùng cho GET /ready
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
