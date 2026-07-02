# ── FastAgent 后端生产 Dockerfile ──
# 基于 Python 3.12 + uv 包管理器
# 构建: docker build -t fastagent-backend -f backend/Dockerfile backend/
FROM python:3.12-slim

WORKDIR /app

# 安装 uv（快速 Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── 依赖安装层（利用 Docker 缓存） ──
COPY pyproject.toml uv.lock /app/
RUN uv sync --no-dev --frozen

# ── 源码复制层 ──
COPY . .

# 启动脚本：先初始化平台基础数据（幂等），再启动 API 服务
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh
CMD ["./docker-entrypoint.sh"]
