# Benchmark & Observability Report — Day 14

**Họ tên:** Nguyễn Ngọc Toàn — 2A202603405
**Ngày chạy:** 2026-11-25 (Bước 1 develop: 07:39–07:45 UTC; Bước 2 production stack: 08:50–09:35 UTC)
**Môi trường:** Laptop Windows 11, Docker Desktop (Docker 27.2.0, VM 12 CPU / 7.5 GB RAM). Agent, `load_test.py` và `run_eval.py` chạy chung một container Linux `python:3.11-slim` (`--cpus 4`) mount thư mục `develop/`, vì Python 3.14 trên Windows không cài được `pydantic==2.9.0`. Agent v1 cổng 8001, v2 cổng 8002, mỗi agent 1 process uvicorn.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Ở tải bình thường p50 ≈ 190 ms, p95 ≈ 220 ms (bảng 2.1, c ≤ 10); 500 ms chừa ~2× dư cho jitter và retrieval mà người dùng chat vẫn thấy "tức thì". Đặt theo p95 vì average che mất tail (bảng 2.2) |
| Error rate `/ask` | < 2 % | Mock LLM có ~1% lỗi upstream (`MOCK_ERROR_RATE=0.01`), đo được 0.33–1.67%; 2% là error budget đủ chứa lỗi upstream ngẫu nhiên nhưng báo động khi lỗi tăng gấp đôi |
| Accuracy trên golden dataset | ≥ 85 % | Ngưỡng của quality gate trong CI ([.github/workflows/eval.yml](.github/workflows/eval.yml)), kèm điều kiện **không có câu regression** so với baseline. Bản đang chạy đạt 100% (23/23) nên 85% là sàn chặn bản tệ đi rõ rệt mà không fail vì 1–2 câu |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Lệnh: `python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json` (`MOCK_SLOW_RATE=0.03` mặc định). SLO: p95 ≤ 500 ms, error rate ≤ 2%.

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.28 | 190.0 | 220.7 | 1702.9 | 0.33% (1× 503) | ✅ PASS |
| 10 | 41.87 | 189.2 | 221.4 | 1694.5 | 1.67% (5× 503) | ✅ PASS |
| 50 | 103.56 | 194.6 | 488.8 | 1708.2 | 0.67% (2× 503) | ✅ PASS |
| 100 | 43.28 | 465.0 | 4766.7 | 5154.1 | 1.67% (5× 503) | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **chỉ tuyến tính ở mức thấp**. Theo định luật Little, RPS ≈ concurrency / latency trung bình: c=1 → 1 / 0.234 s ≈ 4.3 (đo 4.28), c=10 → 10 / 0.239 s ≈ 42 (đo 41.87), đúng vì mock LLM là `asyncio.sleep` nên agent phục vụ song song mà latency không đổi. Từ c=50 bắt đầu lệch:

- **c=50: 103.56 thay vì ~180 RPS.** Mỗi worker chỉ gửi 6 request, nên vài request "slow" 1.7 s ở cuối lượt kéo dài tổng thời gian chạy (2.9 s), làm RPS bị đánh giá thấp. p95 tăng lên 488.8 ms vì 3% request chậm giờ đã chiếm tới gần ngưỡng p95.
- **c=100: RPS giảm còn 43.28, p50 465 ms, p95 4.8 s.** Nút thắt **không nằm ở agent**: đo trong lúc chạy, process agent chỉ dùng ~19% một core, trong khi process `load_test.py` (một event loop Python) dùng **100% một core** và để lại 373 socket TIME_WAIT. Kiểm chứng: chia cùng 100 kết nối đồng thời cho 2 process `load_test.py` × 50 → tổng ≈ 108 + 87 ≈ **195 RPS**, p50 200–226 ms. Tức là latency đo được ở c=100 chủ yếu là thời gian request **xếp hàng trong chính công cụ đo**. Bài học: phải theo dõi tài nguyên của máy tạo tải; benchmark tải cao cần nhiều process/máy tạo tải (như Locust distributed ở mục 5). (Số kiểm chứng 2 process không có file JSON vì chạy không có `--out`; bảng trên chỉ dùng số từ file JSON.)

### 2.2 Tail latency

Lệnh: bật lại v2 với `MOCK_SLOW_RATE=<r>`, rồi `python load_test.py --url http://localhost:8002 --requests 300 --concurrency 20 --out reports/load_v2_slow_<r>.json`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 191.5 | 218.8 | 224.6 |
| 0.03 (mặc định) | 238.5 | 221.9 | 1698.2 |
| 0.1 | 325.5 | 1695.9 | 1714.8 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`. SLO: ✅ / ✅ / ❌ (p95 1695.9 > 500).

**Nhận xét:** **Percentile cao là chỉ số nhạy nhất.** Từ 0 → 3% request chậm: avg chỉ tăng 24.5% (191.5 → 238.5) và p95 gần như không đổi (218.8 → 221.9), nhưng **p99 tăng 7.6 lần** (224.6 → 1698.2) vì 3% > 1% nên p99 rơi đúng vào nhóm chậm. Lên 10%: p95 cũng rơi vào nhóm chậm và tăng 7.75 lần (218.8 → 1695.9), trong khi avg mới tăng 1.7 lần (→ 325.5): nhìn avg vẫn "dưới 500 ms, ổn", nhưng thực tế cứ 10 người thì 1 người chờ ~1.7 s. Average là trung bình của cả nhóm nhanh lẫn chậm, nên tail bị nhóm nhanh "pha loãng"; SLO đặt theo avg sẽ PASS trong khi người dùng đang khó chịu. Vì vậy SLO đặt theo p95/p99, và p99 là cảnh báo sớm nhất (nó đã đỏ ngay ở 3%).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 55.6 | 109.3 | 116.0 |
| Tổng cost (USD) | 0.000383 | 0.000764 | 0.000811 |
| Cost / câu đúng (USD) | 0.00038295 | 0.00003639 | 0.00003524 |
| Latency p50 / p95 (ms) | 165.0 / 189.5 | 197.6 / 215.6 | 187.7 / 215.8 |
| Quality gate | ❌ FAIL (gate 80%) | ✅ PASS (gate 80%, baseline v1, 0 regression) | ✅ PASS (gate 100%, baseline v2, 0 regression) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json` (`--baseline reports/eval_v1.json`), `reports/eval_v2_fixed.json` (`--min-accuracy 1.0 --baseline reports/eval_v2.json`).

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `scaling-03` ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Knowledge base không có tài liệu nào khớp nên v2 trả câu chung chung. Thêm entry kích hoạt bởi `hpa`, `kubernetes`, `autoscal`: "Kubernetes HPA (Horizontal Pod Autoscaler) tự tăng giảm số pod dựa trên mức dùng CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi…" |
| `security-02` ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Thêm entry kích hoạt bởi `jwt`, `api key`: "API key là chuỗi bí mật cố định, không tự hết hạn… JWT là token có chữ ký số, chứa thông tin user (sub, role) và thời điểm hết hạn (exp)…" |

Sửa trong `develop/utils/mock_llm.py` (`KNOWLEDGE_BASE`), không đụng `golden_dataset.jsonl`. Trước khi thêm, kiểm tra các từ khoá kích hoạt chỉ khớp đúng câu cần sửa (`jwt`, `api key` → chỉ `security-02`; `hpa`, `kubernetes` → chỉ `scaling-03`) để retrieval của câu khác không bị đổi tài liệu; kết quả eval cuối: **2 câu được cải thiện, 0 regression**.

**Quality gate trong CI:** [.github/workflows/eval.yml](.github/workflows/eval.yml) chạy trên mọi PR đụng tới `develop/`: bật agent v2 (`MOCK_ERROR_RATE=0` để gate đo chất lượng chứ không phải độ may rủi), rồi `python eval/run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`. `run_eval.py` thoát với **exit code 1** khi accuracy dưới ngưỡng hoặc có câu regression → step fail → check của PR đỏ → bật *Require status checks to pass* cho `main` là PR không merge được. Đã thử: eval v1 với baseline v2 → `exit code = 1`, 22 câu regression, `❌ FAIL`; chạy lại đúng các bước của job với v2 → `exit code = 0`, `✅ PASS`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** retrieval (RAG) đưa accuracy từ 4.3% lên 91.3%, sửa knowledge base lên 100%. v1 không có tài liệu nên chỉ trả lời đúng câu có sẵn trong vài câu mẫu.
- **Chi phí mỗi câu:** v2 dùng gần gấp đôi token (55.6 → 109.3 token/câu, vì prompt có thêm tài liệu) nên tổng cost gấp đôi (0.000383 → 0.000764 USD).
- **Chi phí mỗi câu đúng:** đây mới là chỉ số nên so: v2 rẻ hơn **~10.5 lần** (0.00038295 → 0.00003639 USD), vì v1 tốn tiền cho 22 câu trả lời vô dụng. Sau khi sửa KB, tổng cost tăng nhẹ (+0.000047) nhưng cost/câu đúng còn giảm thêm (0.00003524).
- **Latency:** v2 chậm hơn p50 +32.6 ms, p95 +26.1 ms (bước retrieval ~20 ms + prompt dài hơn), vẫn xa ngưỡng SLO 500 ms.
- Kết luận: trả gấp đôi token và ~30 ms để có câu trả lời đúng là đáng; so hai phiên bản bằng "cost / câu" sẽ chọn sai (v1 trông rẻ hơn).

---

## 4. Observability stack (production)

Bước 2 chạy ngày 2026-11-25, 08:50–09:35 UTC, stack `docker compose -p k5-day14-observability up -d --build` (agent ×2, Nginx, Prometheus v3.16.0, Grafana 13.2.4, Jaeger 2.23.0, Locust 2.47.0) trên cùng máy. Tải nền: Locust headless 30 users, spawn 5/s, giữ suốt các thí nghiệm. Unit test alert: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

Hai chỉnh sửa trước khi chạy được: (1) `production/Dockerfile` thiếu `ENV PYTHONUSERBASE=/home/agent/.local`: `useradd -d /app` làm HOME là `/app` nên Python không thấy package cài `--user` ở `/home/agent/.local` → agent crash `ModuleNotFoundError: No module named 'uvicorn'` và restart liên tục; (2) chép `KNOWLEDGE_BASE` đã sửa ở Exercise 7.3 sang `production/utils/mock_llm.py` (lưu ý K5 số 10).

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png) — 18.4 req/s, error 0.69%, p95 294.47 ms, in-flight 7, 2 instance up
- [x] Một trace chậm trong Jaeger: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus, **2 alert cùng firing** (`AgentHighErrorRate` 17.8% và `LLMCostBurnRateHigh` $2.23/giờ, chụp trong thí nghiệm A): [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Exercise 7.4 (tải nền 30 users, số đọc từ Prometheus):**

1. **p95 vs avg:** p50 171.6 ms, avg 234.8 ms, p95 293.4 ms, nhưng p99 1845 ms. avg cao hơn p50 vì 3% request chậm 1.5–1.7 s kéo trung bình lên; p95 vẫn thấp vì 3% < 5%. Khoảng cách avg ↔ p99 (~8×) chính là tail latency mà avg che mất.
2. **Requests/s theo instance:** 9.09 và 8.89 req/s, Nginx chia gần đều (51/49). Gọi tay 4 lần thấy `X-Served-By` luân phiên `172.19.0.4` ↔ `172.19.0.6`.
3. **Input tokens/s (1412) > output tokens/s (749):** prompt = system prompt + tài liệu retrieval + câu hỏi (≈ 70–90 token), còn câu trả lời chỉ là 1 đoạn tài liệu ngắn (≈ 40–55 token). Với RAG, input luôn lớn hơn output; giá output đắt gấp 4 lần nên vẫn chiếm phần lớn chi phí.
4. **`curl http://localhost:8080/metrics` → `404`:** Nginx có `location = /metrics { return 404; }`. Metric lộ route, lưu lượng, version, chi phí; chỉ Prometheus được scrape trực tiếp từng container trong mạng `obs_net`.

### 4.2 Thí nghiệm "phá hệ thống"

Mỗi thí nghiệm đổi biến bằng `<VAR>=<giá trị> docker compose -p k5-day14-observability up -d agent` (tạo lại container agent), thời gian đo bằng script hỏi `GET /api/v1/alerts` mỗi 5 giây từ lúc chạy lệnh.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical) | pending +30 s, **firing +93 s** (09:02:52 → 09:04:25 UTC) | *Error rate*: 0.6% → 18.0%; *Requests/s theo status code* xuất hiện dải 503 |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (warning) | pending +29 s, **firing +148 s** (09:04:50 → 09:07:18) | *Latency p50/p95/p99*: p95 0.29 s → 1.91 s, p99 1.98 s, p50 vẫn 0.199 s, avg 0.607 s |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (warning) | **firing +144 s** (09:10:29 → 09:12:53), nhưng alert **đã pending từ trước** vì tải nền dao động quanh ngưỡng (xem ghi chú) | *Cost burn rate*: $2.45 → $35.24/giờ (×14.4; tính theo request ×16 vì RPS giảm 18 → 16); p95 0.29 → 0.67 s |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (critical) | pending +10 s, **firing +36 s** (09:08:36 → 09:09:12) | *Instances up* 2 → 1 (`up{instance="172.19.0.6:8000"} = 0`). Nginx trả **28 lỗi 504** cho Locust trong ~50 s pause, nhưng error rate của agent vẫn **0.95%** (xanh) |
| E | `AGENT_VERSION=v1` | **Không có** (sau 150 s) | — | *Retrieval hit ratio* mất (retrieval 18.7/s → 0), *Tokens/s* giảm một nửa (input 1463 → 693), bảng version v2 → v1. p95 còn **tốt hơn** (0.29 → 0.20 s), cost giảm ($2.47 → $1.19/giờ) |

Ghi chú:

- **`LLMCostBurnRateHigh` firing ngay ở tải nền:** 30 users ≈ 18.6 req/s × ~$0.0000365/câu ≈ **$2.44/giờ > ngưỡng $2/giờ** → alert firing từ 08:57:27 khi chưa đổi gì (vì vậy ảnh Alerts có 2 alert cùng firing). Ngưỡng $2/giờ thấp hơn chi phí bình thường của chính bài lab ⇒ alert này là alert giả ở tải 30 users; trong thực tế ngưỡng phải đặt theo budget (vd budget $1000/tháng ≈ $1.4/giờ thì cần alert sớm hơn nữa, còn nếu traffic này là bình thường thì nâng ngưỡng) và nên kèm alert *tăng đột biến so với tuần trước*. Thời gian ở C vì thế không phải "từ inactive"; con số sạch là mức tăng ×14.4.
- **B làm alert cost tự hết:** request chậm khiến user Locust chờ lâu hơn → ít request/giây hơn → chi phí/giờ giảm xuống dưới $2. Các signal ảnh hưởng nhau qua tải khép kín (closed-loop).
- **D:** `docker pause` (không phải `stop`) để container còn trong DNS nhưng không trả lời → `up == 0`. Lỗi 504 xảy ra ở Nginx (`proxy_read_timeout 10s`) cho request đang dở trên instance bị pause; agent không bao giờ xử lý xong nên metric của agent không đếm. Muốn thấy cần metric ở tầng LB (Nginx/ingress) hoặc synthetic check từ ngoài.
- Thời gian tới firing ≈ thời gian để rate() trên cửa sổ 1m/5m vượt ngưỡng + `for`: A (`for: 1m`) ~93 s, B (`for: 2m`) ~148 s, D (`for: 30s`, `up` phản ánh ngay ở lần scrape 5 s sau) ~36 s.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là lỗi **chất lượng**, không phải lỗi hạ tầng: request vẫn 200, nhanh hơn và rẻ hơn, nên mọi Golden Signal đều xanh. Thử gọi v1 câu "Kubernetes HPA scale dựa trên những chỉ số nào?" → trả lời chung chung "Đây là câu trả lời từ AI agent (mock)…". Cách phát hiện:

1. **Chặn trước khi deploy:** quality gate eval trong CI (mục 3) — v1 so với baseline v2 cho exit code 1 với 22 câu regression, không cho merge/deploy.
2. **Giám sát chất lượng khi chạy (online eval):** định kỳ (vd mỗi 15 phút) chạy golden dataset vào bản production thật và đẩy `eval_accuracy` thành metric, alert khi giảm; hoặc LLM-as-judge chấm một mẫu nhỏ traffic thật.
3. **Proxy metric có sẵn trên dashboard:** alert khi *retrieval hit ratio* giảm mạnh (từ ~100% về 0) hoặc *tokens/request* đổi đột ngột; alert khi `agent_info{version}` thay đổi ngoài lịch deploy.
4. **Tín hiệu người dùng:** tỉ lệ thumbs-down / hỏi lại / escalate lên người thật.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được (trong 1000 trace `POST /ask` của 10 phút tải nền, truy vấn Jaeger API v3):

- `trace_id`: `1e76ab35ba0dc8ed5bd2a264e282da04`
- Tổng thời gian: **1719.4 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (1693.6 ms, **98.5%**). `agent.retrieve_context` chỉ 23.5 ms (1.4%). Thuộc tính `gen_ai.request.model=mock-llm-small`, `gen_ai.usage.input_tokens=72`, `output_tokens=40` → đây là request rơi vào nhóm "slow" của LLM upstream, không phải code của agent; tối ưu code agent không giúp được, phải xử lý ở tầng gọi LLM (timeout + retry/hedging, cache, model khác).
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 1e76ab35ba0dc8ed5bd2a264e282da04`):

```json
{"ts": "2026-11-25T08:54:55.818979+00:00", "level": "INFO", "service": "observable-agent", "instance": "ff6c8bf77318", "event": "llm_call", "trace_id": "1e76ab35ba0dc8ed5bd2a264e282da04", "span_id": "9a6cae250f43b196", "request_id": "59691fd1b07b", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 72, "output_tokens": 40, "cost_usd": 3.5e-05, "llm_ms": 1693.1}
{"ts": "2026-11-25T08:54:55.819422+00:00", "level": "INFO", "service": "observable-agent", "instance": "ff6c8bf77318", "event": "http_request", "trace_id": "1e76ab35ba0dc8ed5bd2a264e282da04", "span_id": "9a6cae250f43b196", "request_id": "59691fd1b07b", "method": "POST", "route": "/ask", "status": 200, "ms": 1718.9}
```

Trace lỗi (ảnh `jaeger-error-trace.png`): `trace_id` `a8995572edcd1111378af9144ac3515f`, 109 ms, HTTP 503; span `chat mock-llm-small` (82.2 ms) có `error.type=upstream_unavailable` và event `exception`: `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`. Log cùng `trace_id`:

```json
{"ts": "2026-11-25T08:54:58.049539+00:00", "level": "INFO", "service": "observable-agent", "instance": "ff6c8bf77318", "event": "llm_error", "trace_id": "a8995572edcd1111378af9144ac3515f", "span_id": "cd1d0cb7f18514db", "request_id": "1c40391dd53d", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T08:54:58.049892+00:00", "level": "INFO", "service": "observable-agent", "instance": "ff6c8bf77318", "event": "http_request", "trace_id": "a8995572edcd1111378af9144ac3515f", "span_id": "cd1d0cb7f18514db", "request_id": "1c40391dd53d", "method": "POST", "route": "/ask", "status": 503, "ms": 108.4}
```

(Jaeger 2.23 đã bỏ API cũ `/api/traces`; truy vấn bằng `/api/v3/traces`.)

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Lệnh (sau `docker compose -p k5-day14-observability up -d --scale agent=<n>`, chờ 25 s):
`docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>`

Số liệu dòng `POST /ask` trong `benchmark-results/scale_*_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 (`scale_1_stats.csv`) | 59.57 | 200 | 330 | 1700 | 65 / 7114 (0.91%) |
| 3 (`scale_3_stats.csv`, lần 1) | 53.70 | 210 | 1100 | 2400 | 70 / 6350 (1.10%) |
| 3 (`scale_3_rerun_stats.csv`, lần 2) | 59.32 | 190 | 270 | 1700 | 71 / 7040 (1.01%) |

Phân bổ request trong 2 phút (Prometheus `increase(http_requests_total[2m])`): 1 instance = 7240; 3 instance = 2244 / 1949 / 2261. CPU (docker stats ở giây ~70): 1 instance **40.2%** (giới hạn 0.5 CPU ⇒ dùng ~80% quota); 3 instance 11.9% / 12.3% / 15.0% (~25–30% quota mỗi cái).

**Lưu ý quy trình:** lệnh trong hướng dẫn (không có `--no-deps`) làm `docker compose run` khởi động lại dependency `agent` theo `deploy.replicas: 2` → **cả hai lần đầu thực chất đều chạy 2 instance** (Prometheus thấy 2 instance nhận traffic ở lần "scale_1"). Bảng trên là lần chạy lại với `--no-deps`, đã xác nhận đúng 1 và 3 container.

**Giải thích kết quả:** Scale lên 3 **không cải thiện** RPS hay p95.

- **RPS bị giới hạn bởi bộ tạo tải, không phải server:** Locust là tải khép kín: 100 user, mỗi user chờ 0.5–2 s (TB 1.25 s) giữa các lần gọi → tối đa ≈ 100 / (1.25 + 0.25) ≈ **66 req/s** tổng (đo được 65.4–65.5 req/s aggregated, ~59.5 cho `/ask`). Thêm instance không làm user gửi nhanh hơn.
- **p50/p95 bị giới hạn bởi LLM:** LLM p50 151.6 ms, p95 198 ms ở **cả hai** cấu hình (Prometheus `llm_request_duration_seconds`); p50 end-to-end ≈ LLM + retrieval 20 ms + overhead. p99 1700 ms là 3% request slow của upstream, scale ngang không chạm được. Nút thắt là **LLM upstream**, đúng như gợi ý "xem panel LLM latency".
- Ở 100 users, 1 instance đã dùng ~80% quota CPU 0.5: tăng tải thêm nữa thì 1 instance sẽ bão hoà trước, lúc đó 3 instance mới có lợi (và còn để chịu lỗi: thí nghiệm D).
- **Lần chạy 3 instance đầu tiên** (p95 1100 ms, p99 2400 ms, có lúc RPS tụt còn 37.8 ở giây 93) là nhiễu môi trường trên Docker Desktop: p95 phía agent cũng tăng (625 ms) trong khi LLM p95 không đổi và CPU các agent thấp; chạy lại ngay sau đó với cùng cấu hình cho p95 270 ms. Không tái hiện được nên không kết luận "3 instance chậm hơn"; giữ cả hai file để minh bạch. Bài học: benchmark phải chạy lặp lại vài lần, không tin một lần chạy.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Percentile, không phải trung bình, và đo cả công cụ đo.** 3% request chậm làm p99 tăng 7.6× trong khi avg chỉ +24.5%; còn ở concurrency 100 và ở benchmark scaling, giới hạn thật nằm ở client tạo tải (1 core 100%, tải khép kín ~66 req/s) chứ không ở agent. Số đo chỉ có nghĩa khi biết hệ thống đo bị giới hạn ở đâu và đã chạy lặp lại.
  2. **Metric, trace, log phải nối với nhau bằng `trace_id`.** Dashboard báo p99 cao → Jaeger chỉ ra 98.5% thời gian nằm ở span LLM upstream → log cùng `trace_id` cho token, cost, `llm_ms`. Không có trace thì dễ đi tối ưu nhầm code agent.
  3. **Hạ tầng xanh ≠ người dùng hài lòng.** Thí nghiệm E (v1) làm dashboard còn đẹp hơn trong khi câu trả lời sai hết; thí nghiệm D có 504 ở Nginx mà error rate của agent vẫn xanh. Cần eval chất lượng (CI + online) và giám sát ở tầng LB/synthetic, và alert phải hiệu chỉnh theo tải thật (alert cost $2/giờ đã firing sẵn ở tải nền).
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Chất lượng:** metric `eval_accuracy` từ online eval định kỳ + alert khi giảm; alert *retrieval hit ratio* < 80%; tỉ lệ feedback xấu.
  - **Tầng ngoài:** metric 5xx/504 và latency từ Nginx/ingress, synthetic probe gọi `/ask` từ ngoài mỗi phút; alert theo **SLO burn rate** đa cửa sổ (5m/1h) thay vì ngưỡng tức thời.
  - **LLM:** `llm_requests_total{status="error"}` theo provider + alert, tỉ lệ request chạm timeout, p99 LLM latency; cost theo ngày so với budget tháng và alert *tăng đột biến so với cùng giờ tuần trước* thay vì ngưỡng cố định $2/giờ.
  - **Bão hoà:** CPU throttling của container (`container_cpu_cfs_throttled_*`), memory, in-flight theo instance; alert khi 1 instance > 70% quota để scale trước khi p95 vỡ.
  - **Bảo mật/vận hành:** tỉ lệ 401/429 bất thường (key lộ, bị abuse), alert `agent_info` đổi version ngoài lịch deploy.
