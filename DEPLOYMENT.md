# Deployment Information

## Public URL

https://agent-production-4b653000.up.railway.app

## Platform

Railway. Project `day14-agent` có 2 service:

| Service | Nguồn | Ghi chú |
|---|---|---|
| `agent` | `railway up` từ thư mục [`06-lab-complete/`](06-lab-complete/) (agent Part 6) | Build bằng [`Dockerfile`](06-lab-complete/Dockerfile) theo [`railway.toml`](06-lab-complete/railway.toml) (`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`), domain public trỏ cổng 8000 |
| `Redis` | Railway Redis (`railway add --database redis`) | Chỉ truy cập qua mạng nội bộ `redis.railway.internal:6379` |

Deploy log: build thành công, `Deploy complete`; lúc khởi động mỗi worker log `event="startup" environment="production" ... redis_ok=true`.

## Test Commands

Đặt biến trước khi chạy (key lấy từ Railway dashboard → service `agent` → Variables, **không** ghi vào file này):

```bash
BASE=https://agent-production-4b653000.up.railway.app
AGENT_API_KEY=<key trên Railway>
```

### 4 lệnh tự kiểm (CP6)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đã chạy (2026-11-25):

```text
200
200
401
200
```

### Health check

```bash
curl https://agent-production-4b653000.up.railway.app/health
# {"status":"ok","uptime_seconds":35.1,"environment":"production"}

curl https://agent-production-4b653000.up.railway.app/ready
# {"ready":true,"redis":"ok"}
```

### API test (with authentication)

```bash
curl -X POST https://agent-production-4b653000.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05}}
```

### Rate limiting (10 request / phút / key)

```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" \
    -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"test"}'
done
# 200 200 200 200 200 200 200 200 429 429 429 429 429 429 429
# (2 request ở trên đã dùng 2 lượt → 8 + 2 = 10 rồi bị chặn)
```

Sai key → `401`; `GET /docs` → `404` (tắt khi `ENVIRONMENT=production`).

### Script chấm với URL public

```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://agent-production-4b653000.up.railway.app
# ✅ Public URL: GET https://agent-production-4b653000.up.railway.app/health → 200
# Result: 12/12 tiêu chí đạt · 44/44 checks passed
# 🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

## Environment Variables Set

Đặt trên Railway (service `agent` → Variables), không có trong code hay repo:

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | key ngẫu nhiên 43 ký tự (`secrets.token_urlsafe(32)`), chỉ lưu trên Railway |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` (reference variable → `redis://...@redis.railway.internal:6379`) |
| `ENVIRONMENT` | `production` (bắt buộc có `AGENT_API_KEY`, tắt `/docs`) |
| `PORT` | `8000` (domain public trỏ cổng này; CMD của Dockerfile đọc `${PORT:-8000}`) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `LOG_LEVEL` | `INFO` |

## Xem logs

```bash
railway logs --service agent --lines 50
```

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
