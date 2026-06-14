# ── FastAgent 前端生产 Dockerfile ──
# 多阶段构建：pnpm build → nginx serve
# 构建: docker build -t fastagent-frontend -f frontend/Dockerfile frontend/

# ═══ 阶段 1: 构建 SPA ═══
FROM node:22-alpine AS builder

WORKDIR /app

# 安装 pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# 依赖层（利用 Docker 缓存，package.json 不常变）
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 源码层（src 变更频繁）
COPY . .

# 类型检查 + Vite 构建
RUN pnpm run build

# ═══ 阶段 2: nginx 静态服务 ═══
FROM nginx:1.27-alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置（SPA 路由 + API 反向代理）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
