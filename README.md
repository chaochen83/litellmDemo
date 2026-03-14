# LiteLLM Router 网关（类 OpenRouter 平台）

基于 [LiteLLM](https://github.com/BerriAI/litellm) 的 LLM 路由网关，使用 FastAPI 提供 API、Prometheus+Grafana 做监控，**本地 MySQL + Redis（不用 Docker）**。

## 功能概览

- **API Key 系统**：虚拟 Key 存 MySQL，请求头 `Authorization: Bearer <key>` 鉴权；支持 `POST /api/keys` 创建新 Key
- **Router 策略**：成本优先 / 响应延迟优先 / 最大精度优先 / 合规隔离优先；策略决定主模型与 fallback 顺序，**切换策略即切换 LiteLLM 使用的模型列表**
- **Provider Fallback**：主模型失败时自动按策略顺序尝试下一模型（LiteLLM `fallbacks`）
- **Redis QPS 限流**：按 Key 的 `rate_limit_qps` 在 Redis 内计数，超限返回 429
- **Prometheus 指标**：`/metrics` 暴露 `router_requests_total`、`router_request_latency_seconds`、`router_tokens_total`、`router_rate_limit_hits_total` 等
- **对话接口**：`POST /v1/chat/completions`（OpenAI 兼容），可选传 `model`，不传则按当前策略选主模型
- **国内大模型 Qwen（通义千问）**：通过阿里云 DashScope 接入，配置 `DASHSCOPE_API_KEY` 后，选路策略中会自动包含 `dashscope/qwen-turbo`、`qwen-plus`、`qwen-max` 等模型及 fallback
- **数据看板**：实时请求峰值、今日 token、平均延迟、本月支出；各模型 QPS 曲线；安全围栏记录

## 本地安装（不用 Docker）

### 1. 准备 Python 环境（3.10+）

```bash
# 进入项目目录
cd /path/to/litellmDemo

# 可选：升级 pip（推荐）
python3 -m pip install --upgrade pip

# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt
```

### 2. MySQL 本地安装与建库

- **macOS**: `brew install mysql`，启动：`brew services start mysql`
- **Ubuntu**: `sudo apt install mysql-server && sudo systemctl start mysql`

创建数据库与用户（按需修改密码）：

```bash
mysql -u root -p
```

```sql
CREATE DATABASE router CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- 如用独立用户：
-- CREATE USER 'router'@'localhost' IDENTIFIED BY 'your_password';
-- GRANT ALL ON router.* TO 'router'@'localhost';
-- FLUSH PRIVILEGES;
```

### 3. Redis 本地安装

- **macOS**: `brew install redis`，启动：`brew services start redis`
- **Ubuntu**: `sudo apt install redis-server && sudo systemctl start redis`

（限流依赖 Redis；未配置或不可用时不做 QPS 限流，其余功能正常。）

### 4. 环境变量

复制并编辑 `.env`：

```bash
cp .env.example .env
```

必填示例：

```env
# 至少填一个，用于对话接口（可多填以支持多模型 fallback）
OPENAI_API_KEY=sk-xxx
# Anthropic Claude（https://console.anthropic.com）
ANTHROPIC_API_KEY=sk-ant-xxx
# 国内大模型：阿里云 DashScope / 通义千问 Qwen（https://dashscope.aliyun.com）
DASHSCOPE_API_KEY=sk-xxx

# 与本地 MySQL 一致
DATABASE_URL=mysql+asyncmy://root:你的密码@127.0.0.1:3306/router

# 若已装 Redis
REDIS_URL=redis://127.0.0.1:6379/0
```

### 5. 启动网关

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API 文档：http://localhost:8000/docs  
- 数据看板：http://localhost:8000/  
- 选路配置：http://localhost:8000/routing  
- Prometheus 指标：http://localhost:8000/metrics  

### 6. Prometheus 本地安装（可选）

- **macOS**：`brew install prometheus`，启动：`brew services start prometheus` 或前台运行 `prometheus --config.file=config/prometheus.yml`
- **Debian/Ubuntu**：官方未进默认源，可从 [Prometheus  releases](https://github.com/prometheus/prometheus/releases) 下载对应架构的 `prometheus-*.linux-amd64.tar.gz`，解压后运行：
  ```bash
  tar -xzf prometheus-*.linux-amd64.tar.gz
  cd prometheus-*/
  ./prometheus --config.file=/path/to/litellmDemo/config/prometheus.yml
  ```
  或使用 systemd 管理（将 `prometheus` 二进制放到 `/usr/local/bin`，并写好 unit 文件后）：`sudo systemctl start prometheus`

使用项目配置时，Prometheus 会抓取 `http://localhost:8000/metrics`。

### 7. Grafana 本地安装（可选）

- **macOS**：`brew install grafana`，启动：`brew services start grafana` 或 `grafana-server`
- **Debian/Ubuntu**：使用官方 APT 源安装：
  ```bash
  sudo apt-get install -y apt-transport-https software-properties-common wget
  wget -q -O - https://packages.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
  echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://packages.grafana.com/oss/deb stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
  sudo apt-get update && sudo apt-get install -y grafana
  sudo systemctl daemon-reload && sudo systemctl enable grafana-server && sudo systemctl start grafana-server
  ```
  浏览器打开 http://localhost:3000（默认账号 admin / admin），添加数据源 Prometheus（URL：`http://localhost:9090`），再导入或新建仪表盘查看 `router_*` 指标。

## 还差什么没安装？

按上面步骤自查：

| 组件 | 是否必须 | 检查方式 |
|------|----------|----------|
| Python 3.10+ | 必须 | `python3 --version` |
| pip / venv | 必须 | `pip -V` |
| **MySQL** | 必须 | `mysql --version`，并已建库 `router` |
| **Redis** | 可选 | `redis-cli ping` 得 `PONG` |
| Prometheus | 可选 | `prometheus --version` |
| Grafana | 可选 | 浏览器访问 3000 端口 |

若未装 MySQL：需先安装并建库，否则网关启动或访问接口时会报连库失败。  
若未装 Redis：可不配置 `REDIS_URL`，当前网关可正常提供对话与看板。

## API Key 与对话示例

首次启动会写入**默认 Key**（仅用于本地测试）：`sk-demo-12345678`。请求时必须带鉴权头：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-demo-12345678" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

- 不传 `model` 时，按当前「选路策略」选主模型（如成本优先 → 先试 `gpt-3.5-turbo`，失败再 fallback）。
- 传 `model` 时以该模型为主，fallback 仍为当前策略的模型列表中的其它模型。

创建新 Key（返回的 `key` 只显示一次，请妥善保存）：

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-key", "user_id": "user1", "rate_limit_qps": 20}'
```

请求会经 LiteLLM 路由到对应模型，在 MySQL 记录用量、在 Prometheus 暴露指标；超 QPS 时返回 429。

## 支持的模型（OpenAI / Anthropic / Qwen）

- **OpenAI**：需 `OPENAI_API_KEY`，如 `gpt-3.5-turbo`、`gpt-4o`、`gpt-4o-mini` 等
- **Anthropic（Claude）**：需 `ANTHROPIC_API_KEY`（[Anthropic Console](https://console.anthropic.com)），模型名带 `anthropic/` 前缀：
  - `anthropic/claude-3-5-haiku-20241022`：低成本、低延迟
  - `anthropic/claude-3-5-sonnet-20241022`：均衡、高精度
  - `anthropic/claude-3-opus-20240229`：最高能力
- **国内 Qwen（通义千问）**：需 `DASHSCOPE_API_KEY`（阿里云 [DashScope](https://dashscope.aliyun.com)），模型名带 `dashscope/` 前缀：
  - `dashscope/qwen-turbo`：低成本、低延迟
  - `dashscope/qwen-plus`：均衡
  - `dashscope/qwen-max`：高精度

选路策略中已内置上述三类模型（成本/延迟优先用 Haiku、Qwen-Turbo，精度优先用 Sonnet/Opus、Qwen-Max）；未配置的 provider 会在 fallback 时被跳过。
