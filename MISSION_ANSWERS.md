# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

Trong [01-localhost-vs-production/develop/app.py](01-localhost-vs-production/develop/app.py):

| # | Anti-pattern | Dòng code | Vì sao nguy hiểm |
|---|---|---|---|
| 1 | **Hardcode secret** | L17 `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`, L18 `DATABASE_URL = "postgresql://admin:password123@..."` | Push lên GitHub là lộ key và mật khẩu DB; nằm luôn trong lịch sử git, xoá file không đủ, phải revoke key |
| 2 | **Log ra secret** | L34 `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | Ai đọc được log (log aggregator, đồng nghiệp, nhà cung cấp cloud) đều thấy key |
| 3 | **Config cứng trong code, không đọc env** | L21–22 `DEBUG = True`, `MAX_TOKENS = 500` | Muốn đổi giữa dev/staging/prod phải sửa code và build lại; vi phạm 12-factor "Config" |
| 4 | **`print()` thay cho logging có cấu trúc** | L33, L34, L38 | Không có level, timestamp, không parse được bằng Loki/Datadog; còn log nguyên nội dung câu hỏi/câu trả lời của user |
| 5 | **Không có health check** | (thiếu, ghi chú ở L42) | Platform/load balancer không biết agent còn sống hay đã treo để restart hoặc ngừng route traffic. Đã thử: `GET /health` → **404** |
| 6 | **Bind `localhost`** | L51 `host="localhost"` | Trong container chỉ nhận kết nối từ chính container, bên ngoài (Docker port mapping, cloud router) không gọi vào được; phải dùng `0.0.0.0` |
| 7 | **Port cố định** | L52 `port=8000` | Railway/Render inject `PORT` qua env; port cứng làm app không nhận traffic hoặc đụng cổng |
| 8 | **Bật reload/debug trong mọi môi trường** | L53 `reload=True` | Reloader theo dõi file, tốn tài nguyên, khởi chạy 2 process; không dành cho production |
| 9 | **Không xử lý shutdown (SIGTERM)** | (không có `lifespan` / signal handler) | Khi platform deploy bản mới hoặc scale down, request đang chạy bị cắt ngang |

### Exercise 1.2: Chạy basic version

Lưu ý K5: bản develop nhận `question` qua **query string**, không nhận JSON.

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}   # 422

$ curl -o /dev/null -w '%{http_code}\n' http://localhost:8000/health
404
```

Log của server (thấy rõ secret bị in ra):

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
INFO:     127.0.0.1:50792 - "POST /ask?question=Hello HTTP/1.1" 200 OK
```

**Quan sát:** app chạy được nhưng chưa production-ready. Bằng chứng "it works on my machine" thực tế: lần chạy đầu trên Windows (console encoding `cp1258`), `print()` câu trả lời tiếng Việt ném `UnicodeEncodeError` → request trả **500 Internal Server Error**, và stack trace in ra log. Chỉ khi đặt `PYTHONUTF8=1` mới chạy được. Môi trường khác nhau làm cùng một đoạn code hỏng; đây là lý do cần dev/prod parity (container, cấu hình qua env) và không dựa vào `print()`.

### Exercise 1.3: Comparison table

So sánh [develop/app.py](01-localhost-vs-production/develop/app.py) với [production/app.py](01-localhost-vs-production/production/app.py) + [production/config.py](01-localhost-vs-production/production/config.py):

| Feature | Basic (develop) | Advanced (production) | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | Đọc từ env qua `Settings` tập trung (`config.py` L17–35), có default an toàn | Cùng một image chạy được ở dev/staging/prod chỉ bằng đổi env. Đã thử `PORT=8001 ENVIRONMENT=staging python app.py` → `/health` trả `"environment":"staging"` ở cổng 8001, không sửa dòng code nào |
| Secrets | `OPENAI_API_KEY = "sk-..."` trong code, còn bị `print` ra log | `os.getenv("OPENAI_API_KEY")`, `AGENT_API_KEY`; `.env` bị `.gitignore`, chỉ commit `.env.example`; không log secret (chỉ log `question_length`) | Secret không vào git, không vào log; đổi key không cần deploy lại code |
| Fail fast | Không kiểm tra gì | `validate()` raise `ValueError` nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` (config.py L42–43) | Lỗi cấu hình lộ ra ngay lúc khởi động, không phải khi user đầu tiên gọi |
| Health check | Không có (`/health` → 404) | `GET /health` (liveness: 200 + uptime, version) và `GET /ready` (readiness: 503 khi chưa sẵn sàng) | Platform dùng `/health` để restart container treo, load balancer dùng `/ready` để chỉ route traffic vào instance đã sẵn sàng |
| Logging | `print()` | `logging` với format JSON `{"time","level","msg"}`, ghi sự kiện `agent_request`/`agent_response` | Log aggregator parse/lọc/alert được; có level để tắt debug ở prod |
| Shutdown | Đột ngột, không có hook | `lifespan`: tắt `is_ready` → `/ready` trả 503, chờ request đang chạy xong rồi mới đóng; có handler `SIGTERM` | Rolling deploy/scale down không cắt ngang request của user |
| Host / Port | `localhost:8000` cứng | `HOST` (mặc định `0.0.0.0`), `PORT` từ env | Chạy được trong container và trên Railway/Render (inject `PORT`) |
| Reload / Debug | `reload=True` luôn | `reload=settings.debug`, mặc định `DEBUG=false` | Không chạy reloader và không lộ thông tin debug ở production |
| Input validation | Lỗi encoding → 500 kèm stack trace trong log | Thiếu `question` → `422 {"detail":"question field is required"}` | Lỗi của client trả mã rõ ràng, không ra 500 |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép mới gọi được API từ trình duyệt |

Kết quả chạy bản production:

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":6.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:41:42.266335+00:00"}   # 200

$ curl http://localhost:8000/ready
{"ready":true}   # 200

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{}'
{"detail":"question field is required"}   # 422
```

**Hai điểm bản production vẫn chưa ổn (phát hiện khi chạy thật):**

1. **Log JSON không hiện ra.** `config.py` gọi `logging.warning("OPENAI_API_KEY not set...")` lúc import, trước khi `app.py` gọi `logging.basicConfig(...)`. Lệnh `warning` đầu tiên đã tự cấu hình root logger (format mặc định, level WARNING), nên `basicConfig` sau đó bị bỏ qua: log ra dạng `WARNING:root:...` và mọi `logger.info(...)` dạng JSON bị nuốt. Đã tái hiện bằng một script 3 dòng. Cách sửa: gọi `basicConfig(..., force=True)` hoặc cấu hình logging trước khi import `config`.
2. **`.env` không được nạp.** `config.py` chỉ dùng `os.getenv`, không có `python-dotenv`, nên `cp .env.example .env` không có tác dụng khi chạy `python app.py`; biến phải được export sẵn trong shell (hoặc do Docker/platform inject). Điều này vẫn đúng tinh thần 12-factor (env do môi trường cung cấp), nhưng dễ gây nhầm khi chạy local.

### Checkpoint 1

- **Vì sao hardcode secret nguy hiểm:** secret đi theo code vào git (kể cả lịch sử commit), vào image Docker, vào log; ai có quyền đọc repo đều có key. Bot quét GitHub tìm key public trong vài phút. Sửa bằng cách xoá file là không đủ, phải revoke và tạo key mới.
- **Cách dùng environment variables:** đọc qua `os.getenv("NAME", default)` tập trung trong một `Settings`; liệt kê đủ biến trong `.env.example`; `.env` thật nằm trong `.gitignore`; trên cloud đặt biến ở dashboard của platform.
- **Vai trò của health check:** liveness (`/health`) cho platform biết process còn sống để restart khi treo; readiness (`/ready`) cho load balancer biết instance đã sẵn sàng nhận traffic chưa (lúc khởi động, lúc đang tắt, lúc mất dependency).
- **Graceful shutdown:** khi nhận SIGTERM, app ngừng nhận request mới (readiness → 503), chờ request đang xử lý xong, đóng kết nối rồi mới thoát với exit code 0, thay vì bị kill giữa chừng.

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

Đọc [02-docker/develop/Dockerfile](02-docker/develop/Dockerfile):

1. **Base image:** `python:3.11` (L8), bản Python đầy đủ dựa trên Debian, có sẵn gcc, header, git… nên rất nặng.
2. **Working directory:** `/app` (L11, `WORKDIR /app`). Mọi lệnh `COPY`/`RUN`/`CMD` phía sau chạy tương đối từ đây; kiểm bằng `docker exec`: `/app` chứa `app.py`, `requirements.txt`, `utils/`.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache từng layer và chỉ build lại từ layer đầu tiên có input thay đổi. `requirements.txt` (L14) và `pip install` (L17) đứng trước `COPY app.py` (L20), nên khi chỉ sửa code thì layer cài dependencies vẫn dùng cache, build mất vài giây thay vì cài lại toàn bộ package. Nếu `COPY . .` trước thì mọi lần sửa code đều làm `pip install` chạy lại.
4. **CMD vs ENTRYPOINT:** `CMD ["python", "app.py"]` (L30) là lệnh **mặc định**, bị ghi đè hoàn toàn khi chạy `docker run image <lệnh khác>` (ví dụ `docker run my-agent:develop sh`). `ENTRYPOINT` là chương trình **cố định** của container; tham số của `docker run` (hoặc `CMD`) được nối thêm vào sau nó, muốn đổi phải dùng `--entrypoint`. Hay dùng kết hợp: `ENTRYPOINT ["uvicorn"]` + `CMD ["main:app", "--port", "8000"]`. Cả hai nên viết dạng exec (JSON array) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và run

Build từ gốc repo (lưu ý K5 số 4):

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d --name cp2-dev -p 8000:8000 my-agent:develop
$ docker ps
cp2-dev   my-agent:develop   Up 4 seconds   0.0.0.0:8000->8000/tcp

$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}   # 200

$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.2,"container":true}   # 200
```

Debug container:

```text
$ docker exec cp2-dev sh -c 'whoami; python --version; ls /app'
root                 ← image develop chạy bằng root
Python 3.11.18       ← cùng phiên bản trên mọi máy, khác Python 3.14 trên laptop ở Part 1
app.py  requirements.txt  utils  __pycache__

$ docker logs cp2-dev
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     172.17.0.1:35470 - "POST /ask?question=What%20is%20Docker%3F HTTP/1.1" 200 OK
INFO:     172.17.0.1:35486 - "GET /health HTTP/1.1" 200 OK
```

Câu trả lời tiếng Việt trả về bình thường trong container: môi trường Linux/UTF-8 trong image cố định, không phụ thuộc encoding của máy host như lỗi `cp1258` ở Part 1.

### Exercise 2.3: Multi-stage build & image size comparison

Đọc [02-docker/production/Dockerfile](02-docker/production/Dockerfile):

- **Stage 1 `builder` (L16–29):** từ `python:3.11-slim`, cài thêm `gcc`, `libpq-dev` (build tools), rồi `pip install --user` toàn bộ dependencies vào `/root/.local`. Stage này chỉ để build, không được deploy.
- **Stage 2 `runtime` (L36–72):** bắt đầu lại từ `python:3.11-slim` sạch, tạo user `appuser` không phải root, chỉ `COPY --from=builder /root/.local` (site-packages đã cài), `main.py` và `utils/mock_llm.py`; `USER appuser`, có `HEALTHCHECK`, `CMD uvicorn ... --workers 2`.
- **Vì sao nhỏ hơn:** (1) base `slim` thay vì bản full; (2) gcc, libpq-dev, apt cache và pip nằm ở stage builder, bị bỏ lại, không vào image cuối; (3) chỉ copy đúng file cần chạy. `docker history my-agent:advanced` cho thấy layer dependencies chỉ có **40.8 MB** (`COPY /root/.local`), các layer code chỉ vài KB.

Số đo trên máy (Docker Desktop 27.2.0):

```text
$ docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
$ docker images my-agent
REPOSITORY:TAG      SIZE      IMAGE ID
my-agent:advanced   240MB     211248d81485
my-agent:develop    1.67GB    1c840df31630
```

| Image | `docker images` | `docker image inspect --format '{{.Size}}'` (nén) |
|---|---:|---:|
| Develop (`python:3.11`, single-stage) | **1.67 GB** | 426.3 MB |
| Production (`python:3.11-slim`, multi-stage) | **240 MB** | 57.4 MB |
| Chênh lệch | **giảm ≈ 85.6%** ((1670 − 240) / 1670) | giảm ≈ 86.5% |

- Develop: 1670 MB
- Production: 240 MB
- Difference: ≈ 85.6% nhỏ hơn (image develop nặng gấp ~7 lần)

(Docker Desktop dùng containerd image store nên `docker images` báo dung lượng trên đĩa sau khi giải nén, còn `inspect` báo kích thước nén; tính theo cách nào cũng giảm ~86%.)

Ngoài kích thước, image production còn an toàn hơn: chạy bằng `appuser` (đã kiểm bằng `whoami` trong container), không có compiler, và có `HEALTHCHECK` nên `docker ps` hiện `(healthy)`.

### Exercise 2.4: Docker Compose stack

Chạy trong `02-docker/production/` (lưu ý K5 số 5 và 7: tạo `.env.local` rỗng, đã nằm trong `.gitignore`; đặt `-p` riêng):

```text
$ touch .env.local
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 26 seconds (healthy)   8000/tcp
nginx     nginx:alpine            Up 25 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 37 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 37 seconds (healthy)   6379/tcp
```

**Architecture diagram:**

```text
                 Host (laptop)
                      │  :80 (và :443)
                      ▼
 ┌──────────────────── network "internal" (bridge) ────────────────────┐
 │                                                                     │
 │   ┌──────────────┐  proxy_pass   ┌──────────────────────┐           │
 │   │ nginx:alpine │ ────────────▶ │ agent (FastAPI)      │           │
 │   │ reverse proxy│  agent:8000   │ uvicorn, 2 workers   │           │
 │   │ rate limit   │               │ user appuser         │           │
 │   │ 10 r/s / IP  │               └───┬──────────────┬───┘           │
 │   └──────────────┘                   │ REDIS_URL    │ QDRANT_URL    │
 │                                      ▼              ▼               │
 │                          ┌────────────────┐ ┌──────────────────┐    │
 │                          │ redis:7-alpine │ │ qdrant v1.9.0    │    │
 │                          │ :6379          │ │ :6333            │    │
 │                          │ vol redis_data │ │ vol qdrant_data  │    │
 │                          └────────────────┘ └──────────────────┘    │
 └─────────────────────────────────────────────────────────────────────┘
 Thứ tự start: redis + qdrant (healthy) → agent (depends_on: service_healthy) → nginx
```

**Services nào được start và giao tiếp thế nào:**

- 4 service: `redis`, `qdrant`, `agent`, `nginx`. Compose start `redis` và `qdrant` trước, chờ healthcheck của chúng `healthy`, rồi mới start `agent` (`depends_on: condition: service_healthy`), cuối cùng là `nginx`.
- Tất cả cùng network `internal`; Docker DNS phân giải tên service thành IP container. Kiểm trong container agent: `getent hosts redis qdrant nginx` → `172.19.0.2 redis`, `172.19.0.3 qdrant`, `172.19.0.5 nginx`. Vì vậy agent dùng `redis://redis:6379/0` và `http://qdrant:6333`, Nginx dùng `server agent:8000`.
- Chỉ Nginx publish port ra host (80/443). Agent không publish port: gọi thẳng `http://localhost:8000/health` từ host → không kết nối được (`000`). Mọi traffic phải đi qua Nginx (rate limit, security headers).
- Ghi chú: `main.py` mới chỉ nhận `REDIS_URL`/`QDRANT_URL` qua env chứ chưa thực sự kết nối Redis/Qdrant; stack này minh hoạ kiến trúc.

**Test qua Nginx:**

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":32.1,"version":"2.0.0","timestamp":"2026-11-25T07:48:12.639476"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Header `Server: nginx` (không lộ version vì `server_tokens off`) và các security header chứng tỏ request đi qua Nginx. Log agent thấy request đến từ IP của Nginx `172.19.0.5`:

```text
$ docker compose -p k5-day14-docker logs agent
agent-1  | {"time":"2026-11-25 07:48:12,684","level":"INFO","msg":"{"event": "request", "q_len": 21}"}
agent-1  | INFO:     172.19.0.5:44338 - "POST /ask HTTP/1.1" 200 OK
```

Nhận xét: dòng log "JSON" này thực ra **không phải JSON hợp lệ**, vì `json.dumps(...)` bị nhét vào trong chuỗi `"msg":"..."` mà không escape dấu `"`. Log aggregator sẽ không parse được. Part 6 yêu cầu mỗi dòng log là một JSON object hợp lệ, nên phải tự dựng dict rồi `json.dumps` cả dòng.

Dọn dẹp: `docker compose -p k5-day14-docker down -v`.

### Checkpoint 2

- **Cấu trúc Dockerfile:** `FROM` (base) → `WORKDIR` → copy file khai báo dependencies → `RUN` cài deps → copy source → `EXPOSE` → `USER` → `HEALTHCHECK` → `CMD`. Thứ tự từ ít thay đổi đến hay thay đổi để tận dụng layer cache.
- **Lợi ích multi-stage:** tách môi trường build (có compiler, tool) khỏi môi trường chạy; image cuối nhỏ hơn ~86% (1.67 GB → 240 MB), ít package nên ít lỗ hổng, pull/deploy nhanh hơn.
- **Docker Compose orchestration:** khai báo nhiều service, network, volume trong một file; `depends_on` + healthcheck điều khiển thứ tự khởi động; service gọi nhau bằng tên qua DNS nội bộ; chỉ publish port của entrypoint (Nginx).
- **Debug container:** `docker ps` (trạng thái, healthy), `docker logs <container>` / `docker compose -p <project> logs <service>` (log), `docker exec -it <container> sh` (vào bên trong kiểm file, user, DNS), `docker history <image>` (layer nào nặng).

---

## Part 3: Cloud Deployment

Lớp K5 deploy chính agent Part 6 (thư mục `06-lab-complete/`) ở CP6, sau khi đạt PASS 12/12. Chi tiết: [DEPLOYMENT.md](DEPLOYMENT.md).

### Exercise 3.1: Railway deployment (nền tảng chính)

- **URL:** https://agent-production-4b653000.up.railway.app
- **Screenshot:** [screenshots/dashboard.png](screenshots/dashboard.png), [screenshots/running.png](screenshots/running.png), [screenshots/test.png](screenshots/test.png)

Các bước đã làm (chạy trong `06-lab-complete/`, không `cd` vào `03-cloud-deployment/`):

```bash
npm i -g @railway/cli
railway login
railway init --name day14-agent                  # tạo project, link thư mục hiện tại
railway add --database redis                     # service Redis của Railway
railway add --service agent \
  --variables 'REDIS_URL=${{Redis.REDIS_URL}}' --variables ENVIRONMENT=production \
  --variables PORT=8000 --variables RATE_LIMIT_PER_MINUTE=10 --variables DAILY_BUDGET_USD=1.0
railway variable set AGENT_API_KEY=<key ngẫu nhiên> --service agent   # chỉ đặt trên Railway, không vào repo
railway up --service agent                       # upload + build theo railway.toml (Dockerfile)
railway domain --service agent --port 8000       # → https://agent-production-4b653000.up.railway.app
```

4 lệnh tự kiểm của CP6 với URL public:

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     → 200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      → 200
$ curl ... -X POST "$BASE/ask" (không key)                      → 401
$ curl ... -X POST "$BASE/ask" -H "X-API-Key: $AGENT_API_KEY"   → 200
```

Thêm: sai key → 401; 15 request liên tiếp → `200 ×8, 429 ×7` (đã dùng 2 lượt trước đó, giới hạn 10/phút), chứng tỏ rate limit dùng Redis trên cloud; `/docs` → 404 vì `ENVIRONMENT=production`. `check_production_ready.py --public-url <URL>` → `✅ Public URL: GET .../health → 200`, `12/12 tiêu chí đạt · 44/44 checks passed`.

**Biến môi trường trên cloud:** đặt bằng `railway add --variables` / `railway variable set` (hoặc tab Variables trên dashboard), lưu ở service chứ không trong code. `REDIS_URL=${{Redis.REDIS_URL}}` là *reference variable*: Railway tự thay bằng URL nội bộ của service Redis (`redis.railway.internal`), nên mật khẩu Redis không bao giờ phải copy tay. Đổi biến → Railway tự redeploy.

**Xem logs:** `railway logs --service agent --lines 50` (hoặc tab Deployments → View logs). Log khởi động trên Railway:

```text
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started parent process [470]
[INFO]  ts="2026-11-25T08:30:06.473453+00:00" logger="agent" event="startup" environment="production" port=8000 rate_limit_per_minute=10 daily_budget_usd=1 redis_ok=true
INFO:     Application startup complete.
```

Railway tự parse log JSON của app thành các field (`event`, `redis_ok`...), lọc được theo field: lợi ích trực tiếp của structured logging.

Hai điều gặp khi deploy: (1) đưa key qua stdin trong PowerShell làm dính thêm ký tự xuống dòng (key trên Railway dài 44 thay vì 43 ký tự, client sẽ luôn bị 401), phải đặt lại và so sánh độ dài để chắc; (2) Railway CLI 5.75 cảnh báo `railway.toml` (Config as Code) sẽ bị thay bằng `.railway/railway.ts`, file cũ vẫn chạy tới 2026-12-01.

### Exercise 3.2: So sánh `railway.toml` với `render.yaml`

| | [railway.toml](06-lab-complete/railway.toml) | [render.yaml](06-lab-complete/render.yaml) |
|---|---|---|
| Loại file | Config của **một service** (build + deploy) | **Blueprint** mô tả cả hạ tầng: nhiều service trong một file |
| Build | `[build] builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, `rootDir: 06-lab-complete` (vì Render build từ repo GitHub, phải chỉ thư mục con) |
| Health check | `[deploy] healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, số lần thử | Render tự restart, không cấu hình trong file |
| Redis | **Không khai báo** trong file: tạo bằng `railway add --database redis`, nối bằng reference variable `${{Redis.REDIS_URL}}` | Khai báo luôn service `type: keyvalue` và nối bằng `fromService: {type: keyvalue, name: day14-redis, property: connectionString}` |
| Biến môi trường / secret | **Không có** trong file; đặt bằng CLI/dashboard | Liệt kê trong `envVars`; secret dùng `sync: false` (điền trên dashboard) hoặc `generateValue: true`, không ghi giá trị |
| Nguồn code | `railway up` upload thư mục từ máy (hoặc nối GitHub) | Kéo từ repo GitHub (New → Blueprint), tự deploy lại khi push |
| PORT | Railway inject `PORT`; mình đặt cố định `PORT=8000` và trỏ domain vào 8000 | Render inject `PORT` (mặc định 10000); CMD `${PORT:-8000}` tự theo |

**Vì sao khác:** Railway tách *code config* (file) khỏi *hạ tầng và secret* (project, service, biến nằm trên platform, thao tác bằng CLI); file nhỏ, chỉ nói cách build/chạy. Render đi theo hướng Infrastructure as Code: một Blueprint tái tạo được toàn bộ stack (web + Redis + nối biến) từ repo, nên phải khai báo cả database và danh sách biến, đồng thời cần cơ chế `sync: false` để không ghi secret vào git.

### Exercise 3.3: Cloud Run CI/CD pipeline

Đọc [cloudbuild.yaml](03-cloud-deployment/production-cloud-run/cloudbuild.yaml) và [service.yaml](03-cloud-deployment/production-cloud-run/service.yaml) (không deploy):

1. Push lên `main` kích hoạt Cloud Build trigger. Bước **test** chạy trong `python:3.11-slim`: cài requirements + pytest, `pytest tests/`; test fail thì pipeline dừng, không build.
2. **build** (`waitFor: [test]`): `docker build` gắn 2 tag `ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tái dùng layer.
3. **push**: đẩy cả 2 tag lên Container Registry `gcr.io/$PROJECT_ID`.
4. **deploy**: `gcloud run deploy ai-agent` với image tag `$COMMIT_SHA` (bản đúng commit, dễ rollback), region `asia-southeast1`, min 1 / max 10 instance, 512Mi, 1 CPU, timeout 60s, `ENVIRONMENT=production`, secret `OPENAI_API_KEY` lấy từ Secret Manager.
5. `service.yaml` là bản khai báo (IaC) của cùng service để `gcloud run services replace`: concurrency 80 request/instance, `livenessProbe` → `/health`, `startupProbe` → `/ready`, `AGENT_API_KEY`/`OPENAI_API_KEY` từ Secret Manager qua `secretKeyRef`. Lưu ý: Cloud Run tự đặt `PORT` và coi đó là biến dành riêng, nên khai báo `PORT` trong `env` sẽ bị từ chối khi deploy; chỉ cần `containerPort: 8000`.

### Checkpoint 3

- Deploy thành công lên Railway, URL public trả lời đúng 4 lệnh tự kiểm.
- Biến môi trường và secret đặt trên platform (CLI/dashboard, reference variable cho Redis), không nằm trong code.
- Xem logs bằng `railway logs` hoặc dashboard.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication

Đọc [04-api-gateway/develop/app.py](04-api-gateway/develop/app.py):

- **API key được check ở đâu:** trong dependency `verify_api_key` (L39–54), đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` (L36), so với `API_KEY = os.getenv("AGENT_API_KEY", ...)` (L35). Endpoint `/ask` gắn nó bằng `Depends(verify_api_key)` (L70); `/` và `/health` để public.
- **Sai key thì sao:** thiếu header → **401** "Missing API key" (L44–48); có header nhưng sai → **403** "Invalid API key." (L49–53). Request bị chặn trước khi chạm tới LLM. (Lưu ý: hợp đồng Part 6 yêu cầu *thiếu hoặc sai* đều trả 401, nên Part 6 phải khác bản này.)
- **Rotate key:** key nằm trong env var, không trong code, nên rotate = đặt `AGENT_API_KEY` mới trên platform rồi restart/redeploy, không sửa code. Để không downtime cho client: hỗ trợ tạm 2 key cùng lúc (ví dụ `AGENT_API_KEYS=new,old`), báo client chuyển sang key mới, rồi gỡ key cũ. Nếu key bị lộ thì thu hồi ngay.
- Điểm chưa ổn: L91 `print(f"API Key: {API_KEY}")` in key ra log khi khởi động; default `"demo-key-change-in-production"` khiến app vẫn chạy được khi quên đặt env (nên fail fast thay vì dùng default).

Chạy với `AGENT_API_KEY=secret-key-123 python app.py` (lưu ý K5 số 6):

```text
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

$ curl http://localhost:8000/health
{"status":"ok"}   # 200, public
```

### Exercise 4.2: JWT authentication

Đọc [04-api-gateway/production/auth.py](04-api-gateway/production/auth.py). **JWT flow:**

1. Client `POST /auth/token` với username/password → `authenticate_user` (L70–75) so với `DEMO_USERS` (L27–30); sai → 401.
2. `create_token` (L35–43) tạo payload `{sub, role, iat, exp = now + 60 phút}`, ký bằng HMAC **HS256** với `JWT_SECRET` (L22).
3. Client gửi `Authorization: Bearer <token>` ở mọi request.
4. `verify_token` (L46–67) kiểm chữ ký và hạn bằng `jwt.decode`; không có header → 401 (kèm `WWW-Authenticate: Bearer`), hết hạn → 401, chữ ký sai/token hỏng → 403. Hợp lệ thì trả `{username, role}` cho endpoint.
5. Server **không lưu session**: mọi thông tin nằm trong token đã ký, nên mọi instance có cùng secret đều verify được (stateless, dễ scale). Đổi lại, không thu hồi được token trước khi hết hạn nếu không có blacklist.

Chạy bản production (tài khoản `student` / `demo123`, endpoint `/auth/token`, lưu ý K5 số 6):

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"x"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}

$ curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token": "eyJhbGciOiJI...<redacted>", "token_type": "bearer", "expires_in_minutes": 60, "hint": "<redacted>"}

# payload của token (decode không verify): chỉ là base64, ai cũng đọc được → không đặt secret trong payload
{'sub': 'student', 'role': 'user', 'iat': 1795593223, 'exp': 1795596823}   # exp - iat = 3600 s

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <token>x" ...      # token bị sửa 1 ký tự
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

Nhận xét: response vẫn có `server: uvicorn` dù middleware `security_headers` (app.py L84–85) định xoá: header này do uvicorn thêm sau middleware, muốn ẩn phải chạy uvicorn với `--no-server-header`. Field `budget_remaining_usd` (app.py L160) thực ra trả `usage.total_cost_usd`, tức số **đã dùng** chứ không phải số còn lại (đặt tên sai).

### Exercise 4.3: Rate limiting

Đọc [04-api-gateway/production/rate_limiter.py](04-api-gateway/production/rate_limiter.py):

- **Algorithm:** **Sliding window log** (file ghi là "Sliding Window Counter", nhưng thực chất lưu từng timestamp): mỗi user có một `deque` timestamp (L27); mỗi request bỏ các timestamp cũ hơn 60 giây (L39–40), nếu còn ≥ `max_requests` thì raise 429 kèm `Retry-After` = lúc timestamp cũ nhất ra khỏi cửa sổ (L45–62), không thì ghi timestamp hiện tại (L65). Không có hiện tượng "dồn ở ranh giới phút" như fixed window, nhưng tốn bộ nhớ O(limit) mỗi user.
- **Limit:** `rate_limiter_user` **10 request / 60 giây** (L86); `rate_limiter_admin` 100 request / 60 giây (L87).
- **Bypass cho admin:** app.py L141 chọn limiter theo `role` trong JWT: `role == "admin"` (user `teacher`) dùng limiter 100/phút. Không phải bypass tuyệt đối mà là quota cao hơn; muốn bỏ hẳn thì bỏ qua `limiter.check()` khi role là admin (vẫn nên giữ một trần để chặn token admin bị lộ).

Vòng lặp 20 request với token của `student` (request "Explain JWT" ở 4.2 đã dùng 1 lượt nên còn 9):

```text
Request  1: 200 {"question":"Test 1","answer":"Tôi là AI agent được deploy lên cloud. ...
Request  2: 200 ...
...
Request  9: 200 {"question":"Test 9","answer":"Đây là câu trả lời từ AI agent (mock). ...
Request 10: 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":44}}
Request 11: 429 ...
...
Request 20: 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":41}}
```

Response đầy đủ khi bị chặn:

```text
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795593304
retry-after: 41
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":41}}
```

So sánh với admin (`teacher` / `teach456`), 20 request liên tiếp: `200 × 20`, không bị chặn. Phân quyền: `GET /admin/stats` với token student → **403** "Admin only", với token teacher → 200.

**Hạn chế đã thấy khi chạy:** state nằm trong RAM của process. Ngay khi đang bị 429, restart server rồi gọi lại với **cùng token** → **200**, và `/me/usage` trả về `requests: 1`: bộ đếm rate limit và chi phí đều mất. Token JWT thì vẫn dùng được sau restart (stateless, cùng secret). Chạy nhiều instance thì mỗi instance đếm riêng, user được nhân quota theo số instance. Vì vậy Part 6 yêu cầu state rate limit nằm trong **Redis**.

### Exercise 4.4: Cost guard implementation

**Bản có sẵn** ([04-api-gateway/production/cost_guard.py](04-api-gateway/production/cost_guard.py)):

- Ước lượng chi phí theo token: input $0.15/1M, output $0.60/1M (L20–21); `UsageRecord` gom token theo user theo **ngày** (L24–36), sang ngày mới thì tạo record mới (L53–58) → tự reset.
- `check_budget` (L60–91) chạy **trước** khi gọi LLM: tổng toàn hệ thống ≥ $10/ngày → 503; user ≥ $1/ngày → **402 Payment Required**; ≥ 80% → log warning. `record_usage` (L93–110) cộng token sau khi gọi LLM xong.
- Demo 402 (gọi trực tiếp `CostGuard` với budget nhỏ $0.001, mỗi call 1000 token input + 500 output = $0.00045, vì qua HTTP phải gửi hàng nghìn request mới tới $1 trong khi rate limit 10/phút):

  ```text
  call 1: ok, used $0.00045
  call 2: ok, used $0.0009
  User student at 90% budget          ← warning ở mức 80%
  call 3: ok, used $0.00135           ← vượt budget nhưng vẫn được gọi
  call 4: HTTP 402 {'error': 'Daily budget exceeded', 'used_usd': 0.00135, 'budget_usd': 0.001, 'resets_at': 'midnight UTC'}
  ```

**Hai vấn đề của bản có sẵn:** (1) chỉ so *số đã dùng* với budget, không cộng chi phí của request sắp gọi, nên request cuối được phép đẩy tổng vượt budget ($0.00135 > $0.001); (2) state in-memory nên mất khi restart và không chia sẻ giữa các instance.

**Cách làm theo đề (budget $10/tháng/user, lưu Redis, reset đầu tháng):**

```python
import os
import redis
from datetime import datetime, timezone

r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))

def check_budget(user_id: str, estimated_cost: float) -> bool:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month}"              # key theo tháng → sang tháng mới là key mới = reset
    current = float(r.get(key) or 0)
    if current + estimated_cost > MONTHLY_BUDGET_USD:  # cộng cả request sắp gọi → không vượt trần
        return False
    new_total = r.incrbyfloat(key, estimated_cost)  # INCRBYFLOAT là atomic trong Redis
    r.expire(key, 32 * 24 * 3600)                   # tự dọn key cũ sau ~1 tháng
    if new_total > MONTHLY_BUDGET_USD:              # 2 request đồng thời cùng qua bước GET
        r.incrbyfloat(key, -estimated_cost)         # → hoàn lại và từ chối
        return False
    return True
```

Endpoint gọi `check_budget` với chi phí ước tính trước khi gọi LLM; trả `False` → `HTTPException(402)`. Sau khi có số token thật có thể điều chỉnh chênh lệch bằng `INCRBYFLOAT`. Key theo tháng là cách reset: không cần cron, tháng mới thì key mới bắt đầu từ 0. Vì state nằm trong Redis nên mọi instance thấy cùng một con số và không mất khi restart.

### Checkpoint 4

- **API key authentication:** header `X-API-Key` so với env var, gắn bằng `Depends` vào endpoint cần bảo vệ; đã thấy 401 / 403 / 200.
- **JWT flow:** login → server ký token (sub, role, exp) bằng secret → client gửi `Bearer` → server verify chữ ký + hạn, không cần DB/session. Payload chỉ là base64, không chứa secret.
- **Rate limiting:** sliding window 10 req/phút cho user, 100 cho admin; vượt → 429 + `Retry-After`. Cần Redis để đúng khi restart/scale.
- **Cost guard:** **rate limit bảo vệ tốc độ** (chặn spam, DoS, một user chiếm hết tài nguyên), **cost guard bảo vệ tiền** (chặn tổng chi tiêu). Cần cả hai vì 10 req/phút vẫn là ~14.400 req/ngày: nếu mỗi request dùng prompt dài/model đắt thì vẫn đốt sạch ngân sách mà không bao giờ chạm rate limit; ngược lại cost guard không chặn được spam request rẻ làm quá tải server.

---

## Part 5: Scaling & Reliability

### Exercise 5.1-5.5: Implementation notes

Môi trường test: app develop chạy trong container Linux (`my-agent:develop`, Python 3.11, mount `05-scaling-reliability/develop/`) để gửi được **SIGTERM thật**; Python trên Windows không gửi được SIGTERM (lưu ý K5 số 2).

#### Exercise 5.1: Health checks

[05-scaling-reliability/develop/app.py](05-scaling-reliability/develop/app.py) đã có sẵn hai probe:

- `GET /health` (L104–144), **liveness**: trả 200 khi process còn chạy, kèm uptime, version, timestamp và check bộ nhớ (`psutil`; không có thì ghi chú). Không kiểm dependency bên ngoài, vì nếu Redis chết mà `/health` fail thì platform sẽ restart container liên tục mà không giải quyết được gì.
- `GET /ready` (L147–168), **readiness**: trả 503 khi `_is_ready = False` (đang khởi động hoặc đang shutdown), 200 kèm số `in_flight_requests` khi sẵn sàng. Bản production ([production/app.py](05-scaling-reliability/production/app.py) L208–215) còn `ping()` Redis, mất Redis → 503.

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T07:59:14.441649+00:00","checks":{"memory":{"status":"ok","note":"psutil not installed"}}}   # 200

$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}   # 200 (đếm cả chính request /ready, vì middleware tăng bộ đếm cho mọi request)

$ time curl -X POST "http://localhost:8000/ask?question=hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}   # 200
real 0m3.068s     ← mock LLM có delay 3 giây
```

**Liveness vs readiness:** liveness trả lời "process có cần restart không?" → fail thì platform **giết và khởi động lại** container. Readiness trả lời "có nên gửi traffic vào đây không?" → fail thì load balancer **ngừng route** tới instance đó nhưng không giết nó (đang khởi động, đang tắt, mất Redis tạm thời). Part 6 yêu cầu đúng điều này: `/health` vẫn 200 khi Redis chết, còn `/ready` phải 503.

#### Exercise 5.2: Graceful shutdown

Cơ chế có sẵn trong develop/app.py:

1. uvicorn bắt SIGTERM (`handle_sigterm` L175–187 chỉ log thêm), ngừng nhận kết nối mới và chờ request đang xử lý xong (`timeout_graceful_shutdown=30`, L198).
2. Sau đó chạy phần shutdown của `lifespan` (L54–66): `_is_ready = False` → `/ready` trả 503, chờ `_in_flight_requests` (đếm bởi middleware `track_requests`, L72–81) về 0, tối đa 30 giây.
3. Process thoát với exit code 0.

**Test (2 request song song, SIGTERM sau 0,5 giây, rồi gửi thêm 1 request mới):**

```text
$ docker kill --signal=SIGTERM cp4-dev      # sau 0.5s
new request during shutdown: 000            ← không nhận kết nối mới
req1: {"answer":"Agent đang hoạt động tốt! ..."} [200] t=3.03s   ← hoàn thành dù đã nhận SIGTERM
req2:  [000] t=3.01s                                             ← BỊ CẮT
container: status=exited exit=0

INFO:     172.17.0.1:57370 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     172.17.0.1:34010 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Finished server process [1]
INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Request thứ hai bị mất. Nguyên nhân:** `ask_agent` được khai báo `async def` (L94) nhưng bên trong gọi `ask()` dùng `time.sleep(3)` (blocking). Hàm blocking trong `async def` chặn cả event loop: trong 3 giây đó server không đọc được request nào khác, nên request 2 vẫn nằm trong hàng đợi kết nối khi SIGTERM tới và bị đóng khi process thoát. Kiểm chứng khi không kill: 2 request song song mất **6 giây** (chạy nối tiếp) thay vì 3, và `GET /health` gửi trong lúc `/ask` đang chạy phải chờ **2,7 giây**. Như vậy health check cũng có thể timeout dưới tải, và platform sẽ tưởng container chết.

**Cách sửa (đã thử trên bản sao trong scratchpad, không sửa code mẫu):** đổi `async def ask_agent` thành `def ask_agent` để FastAPI chạy nó trong threadpool (hoặc giữ `async` và dùng `await asyncio.to_thread(ask, question)` / client LLM async). Kết quả sau khi sửa:

```text
concurrent req1 [200] t=3.02s       ← 2 request song song giờ chỉ mất 3 giây
concurrent req2 [200] t=3.03s

### SIGTERM test
new request during shutdown: 000
req1 [200] t=3.03s                  ← cả hai request in-flight đều hoàn thành
req2 [200] t=3.03s
container status=exited exit=0

INFO:     Shutting down
INFO:     Waiting for connections to close. (CTRL+C to force quit)
INFO:     172.17.0.1:42248 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     172.17.0.1:42264 - "POST /ask?question=hello HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO:     Finished server process [1]
```

Bài học cho Part 6: graceful shutdown chỉ bảo vệ được request **đã được server nhận xử lý**; endpoint gọi LLM phải không chặn event loop. Ngoài ra uvicorn phải là PID 1 trong container (CMD dạng exec), nếu không SIGTERM của `docker stop` không tới được uvicorn.

#### Exercise 5.3: Stateless design

Bản [production/app.py](05-scaling-reliability/production/app.py) đã refactor thành stateless:

- Session và conversation history lưu trong Redis, key `session:{session_id}`, `SETEX` TTL 1 giờ (`save_session` L59–65, `load_session` L68–73); giữ tối đa 20 message (L86–87).
- Instance không giữ gì về user trong RAM; mỗi request mang `session_id`, instance nào nhận cũng đọc/ghi cùng một chỗ. `INSTANCE_ID` (L52) chỉ để quan sát.

**Vì sao state trong RAM hỏng khi chạy nhiều instance:** mỗi instance là một process riêng với bộ nhớ riêng. Load balancer round-robin nên turn 1 vào instance A (lưu history trong RAM của A), turn 2 vào instance B (không thấy history). Thêm nữa: restart/deploy/scale-down làm mất sạch state. Part 4 đã chứng minh điều này với rate limiter in-memory (restart lúc đang 429 → được 200 lại ngay).

**Hạn chế còn lại:** code có fallback sang dict in-memory nếu không kết nối được Redis lúc khởi động (L42–45), tức là âm thầm quay lại stateful khi Redis lỗi. Production nên fail (`/ready` 503) thay vì fallback. `append_to_history` đọc–sửa–ghi cả session (L76–89) nên hai request đồng thời cùng session có thể ghi đè nhau; dùng `RPUSH` + `LTRIM` trên Redis list sẽ atomic hơn.

#### Exercise 5.4: Load balancing

Trong `05-scaling-reliability/production/` (lưu ý K5 số 5 và 7: `touch .env.local`, cổng **8080**, endpoint **`POST /chat`**):

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
$ docker compose -p k5-day14-scaling ps
k5-day14-scaling-agent-1   Up 22 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 21 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 21 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 20 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 33 seconds (healthy)   6379/tcp
```

10 request qua Nginx (header `X-Served-By` do Nginx thêm, `served_by` do agent trả):

```text
req 1: nginx-> 172.19.0.5:8000 | served_by = instance-b7c499 | storage = redis
req 2: nginx-> 172.19.0.3:8000 | served_by = instance-c3518f | storage = redis
req 3: nginx-> 172.19.0.4:8000 | served_by = instance-1f7396 | storage = redis
req 4: nginx-> 172.19.0.5:8000 | served_by = instance-b7c499 | storage = redis
...
req 10: nginx-> 172.19.0.5:8000 | served_by = instance-b7c499 | storage = redis

$ docker compose -p k5-day14-scaling logs agent | grep 'POST /chat'   (đếm theo instance)
      3 agent-1
      4 agent-2
      3 agent-3
```

**Cách Nginx phân tải:** `upstream agent_cluster { server agent:8000; }` ([nginx.conf](05-scaling-reliability/production/nginx.conf) L7–11). Docker DNS trả về IP của cả 3 container cho tên `agent`, Nginx đưa cả 3 vào upstream và chia **round-robin** (thứ tự .5 → .3 → .4 lặp lại đúng như trên). Chỉ Nginx publish cổng ra host; agent không lộ cổng.

**Khi 1 instance chết:** `docker stop k5-day14-scaling-agent-1` (SIGTERM, agent-1 thoát với exit code 0, log `Instance instance-c3518f shutting down`), rồi tiếp tục cùng một session:

```text
turn 3 -> instance-1f7396 [200] 0.107s
turn 4 -> instance-b7c499 [200] 0.111s
turn 5 -> instance-1f7396 [200] 3.223s   ← Nginx thử IP đã chết trước, timeout, rồi chuyển sang instance khác
turn 6 -> instance-b7c499 [200] 0.144s
turn 7 -> instance-1f7396 [200] 0.116s
turn 8 -> instance-b7c499 [200] 0.115s
history count: 14                         ← không mất message nào

nginx-1 | [error] upstream timed out (110: Operation timed out) while connecting to upstream ... upstream: "http://172.19.0.3:8000/chat"
```

Traffic tự chuyển sang 2 instance còn lại nhờ `proxy_next_upstream error timeout http_503` (L23) và history vẫn đủ vì nằm trong Redis. Nhưng Nginx chỉ resolve `agent` **một lần lúc khởi động** (directive `resolver` chỉ có tác dụng khi `proxy_pass` dùng biến), nên vẫn giữ IP đã chết trong upstream. Cứ khi hết `fail_timeout` (mặc định 10 giây) nó lại thử IP đó, làm một request chậm thêm ~3 giây. Muốn sạch hơn: dùng `server agent:8000 resolve` (Nginx ≥ 1.27.3, như stack Part 7) hoặc health check chủ động. (Phụ: field `turn` trong response lệch 1, vì `history` được đọc **sau** khi đã thêm câu hỏi hiện tại rồi lại `+ 1`, app.py L140–154.)

#### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: 203a09fa-9a82-45a5-921f-62531239e4b3

Request 1: [instance-1f7396]   Q: What is Docker?
Request 2: [instance-b7c499]   Q: Why do we need containers?
Request 3: [instance-c3518f]   Q: What is Kubernetes?
Request 4: [instance-1f7396]   Q: How does load balancing work?
Request 5: [instance-b7c499]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-b7c499', 'instance-1f7396', 'instance-c3518f'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 câu trong **cùng một session** được 3 instance khác nhau xử lý xen kẽ (round-robin), nhưng history đọc lại có đủ **10 message** (5 user + 5 assistant) đúng thứ tự. Nếu state nằm trong RAM, mỗi instance chỉ thấy phần của mình (khoảng 2 + 2 + 1 lượt) và history đọc ra sẽ thiếu tùy instance nào trả lời request `GET /history`. Script không tự tắt instance nào; phần "instance chết" mình đã tự thử ở 5.4 (history vẫn đủ 14/14 message sau khi tắt agent-1).

Dọn dẹp: `docker compose -p k5-day14-scaling down`.

### Checkpoint 5

- **Health + readiness:** `/health` = liveness (process sống, không phụ thuộc Redis), `/ready` = readiness (503 khi khởi động, đang tắt hoặc mất Redis).
- **Graceful shutdown:** SIGTERM → ngừng nhận kết nối mới → chờ request đang chạy xong → exit 0. Đã thấy bằng SIGTERM thật trong container, và thấy nó chỉ đúng khi endpoint không chặn event loop.
- **Stateless:** state trong Redis có TTL, instance nào cũng phục vụ được mọi session; đã chứng minh qua 3 instance và cả khi tắt 1 instance.
- **Load balancing với Nginx:** round-robin qua Docker DNS, tự bỏ qua instance lỗi nhờ `proxy_next_upstream`; hạn chế là resolve DNS một lần nên còn chậm khi một IP chết.

---

## Part 6: Final Project — Production-ready agent

### Kết quả `check_production_ready.py` (chạy đầy đủ, có Docker)

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số dòng chi tiết từ cùng lần chạy:

```text
✅ Docker: build image thành công — 47s
✅ Docker: image < 500 MB — 63 MB
✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)
✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON
✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 1.0s
```

Chạy lại sau khi deploy (CP6) với `--public-url https://agent-production-4b653000.up.railway.app`: `✅ Public URL: GET .../health → 200`, **`12/12 tiêu chí đạt · 44/44 checks passed`**.

**Môi trường chạy script chấm:** máy mình không có distro Ubuntu trong WSL2 (chỉ có `docker-desktop`), còn Python 3.14 trên Windows không cài được `pydantic==2.9.0` và không gửi được SIGTERM. Vì vậy mình chạy **script nguyên bản, không sửa** trong một container Linux (`python:3.11-slim` + Docker CLI, `--network host`, mount Docker socket), tương đương WSL2: `os.name == "posix"`, SIGTERM thật, build và chạy image bằng Docker của máy. Lab Coach chạy lại trực tiếp `python check_production_ready.py` trong `06-lab-complete/` vẫn được kết quả này.

### Thiết kế

| Tiêu chí | Cách làm | File |
|---|---|---|
| Config | `Settings` đọc `PORT`, `ENVIRONMENT`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `LOG_LEVEL` từ env; `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` thì không khởi động (fail fast) | [app/config.py](06-lab-complete/app/config.py) |
| API key | `APIKeyHeader("X-API-Key")`, so bằng `hmac.compare_digest` (không lộ qua timing); thiếu, sai hoặc server chưa cấu hình key → **401** | [app/auth.py](06-lab-complete/app/auth.py) |
| Redis | `redis.from_url` chỉ tạo pool, không kết nối lúc import → container khởi động được khi chưa có Redis; timeout 1 giây | [app/redis_client.py](06-lab-complete/app/redis_client.py) |
| Rate limit | Sliding window bằng sorted set theo **hash** của API key (không lưu key thô); `ZREMRANGEBYSCORE` + `ZADD` + `ZCARD` + `EXPIRE` trong một `MULTI/EXEC` nên 2 worker không cùng lọt qua; vượt → **429** + `Retry-After`; request bị từ chối không tính vào quota | [app/rate_limiter.py](06-lab-complete/app/rate_limiter.py) |
| Cost guard | Tổng chi phí theo ngày UTC trong key `cost:YYYY-MM-DD` (sang ngày mới = key mới = reset); kiểm tra **cả chi phí ước tính của request sắp gọi** (sửa lỗi cho vượt budget đã thấy ở Part 4); `INCRBYFLOAT` atomic; vượt → **402** | [app/cost_guard.py](06-lab-complete/app/cost_guard.py) |
| Health / Ready | `/health` luôn 200, không đụng Redis; `/ready` 503 khi `PING` Redis lỗi hoặc đang tắt | [app/main.py](06-lab-complete/app/main.py) |
| Logging | `JsonFormatter` tự viết: mỗi dòng là một `json.dumps` của dict (`ts`, `lvl`, `event`, các field), kể cả traceback (escape `\n` nên vẫn một dòng); middleware log `method`, `path`, `status`, `ms`; không log API key hay nội dung câu hỏi | app/main.py |
| Xử lý lỗi | Input sai → 422 của Pydantic (độ dài 1–2000); Redis lỗi → 503 `Dependency unavailable`; lỗi khác → 500 `Internal server error`, không lộ stack trace; `/docs` tắt khi `ENVIRONMENT=production` | app/main.py |
| Graceful shutdown | Không tự đăng ký SIGTERM handler (để uvicorn tự xử lý: ngừng nhận kết nối, chờ request đang chạy). `/ask` là `def` để chạy trong threadpool, không chặn event loop (bài học Part 5). `lifespan` đóng Redis pool khi tắt. Dockerfile dùng `exec uvicorn` để uvicorn là PID 1 | app/main.py, Dockerfile |
| Docker | Multi-stage: builder tạo `/opt/venv`, runtime `python:3.11-slim` chỉ copy venv + `app/` + `utils/`; user `app` non-root; `HEALTHCHECK` gọi `/health` theo `PORT`; `CMD` nghe `${PORT:-8000}`, 2 worker | [Dockerfile](06-lab-complete/Dockerfile), [.dockerignore](06-lab-complete/.dockerignore) |
| Compose | `agent` build từ Dockerfile, `env_file: .env` (`required: false`), `REDIS_URL=redis://redis:6379/0`, `depends_on` Redis `service_healthy`; `redis:7-alpine` có healthcheck và volume | [docker-compose.yml](06-lab-complete/docker-compose.yml) |
| Deploy config | `railway.toml` (builder `DOCKERFILE`, `healthcheckPath = "/health"`); `render.yaml` (web + Key Value, `AGENT_API_KEY` dùng `sync: false`, `REDIS_URL` lấy từ service Redis) | [railway.toml](06-lab-complete/railway.toml), [render.yaml](06-lab-complete/render.yaml) |

### Test thêm bằng `docker compose up` (ngoài script chấm)

```text
$ docker compose -p k5-day14-final up -d --build      # .env tạm có AGENT_API_KEY ngẫu nhiên, đã xoá sau test
agent Up 8 seconds (healthy)
redis Up 14 seconds (healthy)

GET  /health                    → 200 {"status":"ok","uptime_seconds":7.3,"environment":"staging"}
GET  /ready                     → 200 {"ready":true,"redis":"ok"}
POST /ask  (không key)          → 401 {"detail":"Missing or invalid API key. Include header: X-API-Key: <your-key>"}
POST /ask  (sai key)            → 401
POST /ask  (đúng key)           → 200 {"question":"What is deployment?","answer":"Deployment là quá trình ...","usage":{"input_tokens":4,"output_tokens":19,"cost_usd":1.2e-05}}
POST /ask  {"question":""}      → 422 string_too_short
POST /ask  {bad json            → 422 json_invalid
POST /ask  {"q":1}              → 422 missing question
11 request liên tiếp            → 200 ×9, 429 ×2   (request "đúng key" ở trên đã dùng 1 lượt / 10)
                                  HTTP/1.1 429 Too Many Requests, retry-after: 58

# docker compose stop redis
GET  /health                    → 200   (liveness không phụ thuộc Redis)
GET  /ready                     → 503 {"ready":false,"redis":"unavailable"}
POST /ask                       → 503 {"detail":"Dependency unavailable, try again later"}   (không có stack trace)
# docker compose start redis
GET  /ready                     → 200

$ docker compose exec agent whoami     → app          (non-root)
$ ls -a /app                           → app  utils   (không có .env, tài liệu, script chấm)
```

Log của agent (mỗi dòng là một JSON object):

```text
{"ts": "2026-11-25T08:17:56.972231+00:00", "lvl": "INFO", "logger": "agent", "event": "request", "method": "GET", "path": "/health", "status": 200, "ms": 1.6}
{"ts": "2026-11-25T08:18:04.884734+00:00", "lvl": "ERROR", "logger": "agent", "event": "dependency_error", "path": "/ask", "error": "ConnectionError"}
{"ts": "2026-11-25T08:18:04.885203+00:00", "lvl": "INFO", "logger": "agent", "event": "request", "method": "POST", "path": "/ask", "status": 503, "ms": 3833.6}
```

**Giới hạn đã biết:** khi container Redis bị *stop* trong Compose, tên `redis` biến khỏi Docker DNS và riêng bước tra DNS mất ~4 giây (đo: `getaddrinfo('redis')` = 3.97s), nên `/ready` trả 503 sau ~4 giây chứ không phải 1 giây như `socket_connect_timeout`. Trên cloud, hostname của Redis vẫn tồn tại khi Redis lỗi nên probe fail nhanh. Cost guard tính tổng của cả agent (bảo vệ hoá đơn), chưa chia budget theo từng user.

---

## AI log

| # | Hỏi gì | Nhận gì | Tự sửa / tự kiểm tra thế nào |
|---|---|---|---|
| 1 | Nhờ Claude Code (Opus 5.5) làm CP1: đọc code Part 1, chạy bản develop và production, viết mục Part 1 | Danh sách anti-pattern kèm số dòng, bảng so sánh, output curl | Mọi output trong mục Part 1 là từ lệnh chạy thật trên máy (Windows, Python 3.14). Lỗi `UnicodeEncodeError` và lỗi `basicConfig` bị bỏ qua là phát hiện khi chạy; lỗi logging được tái hiện riêng bằng script nhỏ. Số dòng đối chiếu lại với file |
| 2 | Nhờ Claude Code làm CP2: đọc Dockerfile/Compose, build 2 image, chạy container và stack Compose, viết mục Part 2 | Câu trả lời 2.1, số đo image, sơ đồ kiến trúc, output test qua Nginx | Số MB lấy từ `docker images` và `docker image inspect` chạy thật trên máy; DNS nội bộ kiểm bằng `getent hosts` trong container; việc agent không publish port kiểm bằng curl từ host; lỗi log JSON lồng chuỗi thấy trực tiếp trong `docker compose logs` |
| 3 | Nhờ Claude Code làm CP3: đọc code Part 4, chạy bản develop (API key) và production (JWT, rate limit, cost guard), viết mục Part 4 | Output `curl -i` 401/403/200/429, giải thích JWT flow, thuật toán rate limit, đề xuất cost guard bằng Redis | Mọi output là lệnh chạy thật; token đã che. Mất state khi restart kiểm bằng cách restart server lúc đang 429. Lỗi cost guard cho vượt budget kiểm bằng script gọi `CostGuard` với budget nhỏ. Code Redis trong 4.4 là đề xuất, chưa chạy; sẽ kiểm khi làm Part 6 |
| 4 | Nhờ Claude Code làm CP4: chạy probe và test SIGTERM của bản develop trong container Linux, chạy stack 3 instance + Nginx + Redis, `test_stateless.py`, thử tắt 1 instance | Output probe, log graceful shutdown, phân bổ round-robin, kết quả test stateless và failover | Request bị cắt khi SIGTERM được tìm ra nguyên nhân bằng thí nghiệm (2 request song song mất 6s, `/health` chờ 2,7s), và cách sửa `async def` → `def` được kiểm trên bản sao trong scratchpad, không sửa code mẫu. Phân bổ request đếm từ `docker compose logs`; failover kiểm bằng `docker stop` một instance giữa session |
| 5 | Nhờ Claude Code làm CP5: hoàn thành các TODO trong `06-lab-complete/` (config, auth, Redis, rate limit, cost guard, `/health`, `/ready`, log JSON, graceful shutdown, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) | Code cho cả 12 tiêu chí; script chấm chạy trong container Linux | `check_production_ready.py` không bị sửa (kiểm bằng `git status`). Kết quả PASS 12/12 lấy từ lần chạy script nguyên bản. Tự test thêm qua `docker compose`: 401/200/422/429/503, `/health` vẫn 200 khi tắt Redis, log JSON, user non-root. Việc `/ready` chậm 4 giây khi tắt Redis được đo và tìm ra nguyên nhân là DNS. Phải giải thích được từng file trong `app/` khi Lab Coach hỏi |
| 6 | Nhờ Claude Code làm CP6: deploy agent Part 6 lên Railway bằng CLI (project, Redis, biến môi trường, domain), chạy test với URL public, viết `DEPLOYMENT.md` và mục Part 3 | URL public, output 4 lệnh tự kiểm, bảng so sánh `railway.toml`/`render.yaml`, mô tả pipeline Cloud Run | Tự đăng nhập Railway. Key sinh ngẫu nhiên, không ghi vào repo. Lỗi key dính ký tự xuống dòng được phát hiện bằng cách so độ dài key local và remote. Lỗi SSL của Python Windows với URL public được kiểm lại bằng `openssl` (cert còn hạn tới 2026-12-26) và chạy script chấm trên Linux. Chưa deploy Render (dùng phương án so sánh file) |
| 7 | Nhờ Claude Code làm CP7: thêm metric `agent_question_length_chars` (7.1), load test 4 mức concurrency và 3 mức `MOCK_SLOW_RATE` (7.2), eval v1/v2, sửa `KNOWLEDGE_BASE`, job CI quality gate (7.3), điền mục 1–3 của `BENCHMARK_REPORT.md` | 10 file JSON trong `develop/reports/`, phân tích tail latency và trade-off v1/v2, `.github/workflows/eval.yml` | Mọi số trong `BENCHMARK_REPORT.md` đọc lại từ file JSON bằng script. RPS giảm ở c=100 được điều tra bằng cách đo CPU (agent ~19%, client 100%) và chạy 2 client song song (~195 RPS) để chứng minh nút thắt nằm ở công cụ đo. Từ khoá KB mới được kiểm tra không khớp câu khác trước khi sửa; không sửa `golden_dataset.jsonl`. Các bước của job CI được chạy thử trong container (exit 0) và trường hợp fail (exit 1) |
| 8 | Nhờ Claude Code làm CP8: dựng stack Prometheus/Grafana/Jaeger/Locust, chạy 5 thí nghiệm A–E, benchmark scaling 1 vs 3 instance, chụp 4 ảnh bằng trình duyệt tự động (Playwright), điền mục 4–6 của `BENCHMARK_REPORT.md` | 4 ảnh trong `screenshots/`, CSV Locust, thời gian tới firing của từng alert, phân tích trace và scaling | Sửa lỗi `PYTHONUSERBASE` trong `production/Dockerfile` sau khi đọc log crash. Thời gian alert đo bằng script hỏi Prometheus API mỗi 5 giây. Phát hiện lệnh `docker compose run` (thiếu `--no-deps`) làm 2 lần benchmark đầu thực chất đều chạy 2 instance, nên chạy lại và xác nhận số container + phân bổ request qua Prometheus. Lần chạy 3 instance bị nhiễu được chạy lại và giữ cả hai file. Số trong báo cáo đọc lại từ CSV/JSON/Prometheus |
