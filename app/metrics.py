from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY

# 请求计数（按模型）
REQUEST_COUNT = Counter(
    "router_requests_total",
    "Total chat requests",
    ["model", "user_id"],
)
# 延迟
REQUEST_LATENCY = Histogram(
    "router_request_latency_seconds",
    "Request latency in seconds",
    ["model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)
# Token 用量
TOKEN_TOTAL = Counter(
    "router_tokens_total",
    "Total input+output tokens",
    ["model", "user_id"],
)
# 当前 QPS（可选，由 Prometheus 用 rate() 算）
REQUEST_ACTIVE = Gauge(
    "router_requests_active",
    "Active requests",
    ["model"],
)
# 限流触发次数
RATE_LIMIT_HITS = Counter(
    "router_rate_limit_hits_total",
    "Total rate limit rejections",
    ["user_id"],
)


def get_metrics():
    return generate_latest(REGISTRY)
