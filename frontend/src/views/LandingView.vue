<script setup lang="ts">
/** FastAgent 公共落地页
 *
 *  非登录用户访问根路径时的引导页面，介绍产品定位、核心能力和接入方式。
 *  已登录用户会自动跳转到工作台，不会看到此页面。
 */
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <div class="landing-page">
    <!-- ── Hero 区 ── -->
    <header class="hero">
      <nav class="top-nav">
        <span class="logo">FastAgent</span>
        <div class="nav-links">
          <el-button text @click="router.push('/login')">登录</el-button>
          <el-button type="primary" @click="router.push('/login')">登录控制台</el-button>
        </div>
      </nav>
      <div class="hero-content">
        <h1>AI 智能客服，驱动销售转化</h1>
        <p class="hero-sub">
          多租户、全渠道 AI Agent SaaS 平台 —— 接入企业微信，7×24 小时自动回复，
          商品推荐、知识问答、订单处理、智能跟单全链路闭环。
        </p>
        <div class="hero-actions">
          <el-button size="large" type="primary" @click="router.push('/login')">登录控制台</el-button>
          <el-button size="large" text @click="router.push('/login')">已有账号？登录</el-button>
        </div>
      </div>
    </header>

    <!-- ── 核心能力区 ── -->
    <section class="features">
      <h2>核心能力</h2>
      <div class="feature-grid">
        <article>
          <h3>全渠道接入</h3>
          <p>企业微信自建应用一键接入，客户消息直达工作台。后续可扩展 Web/公众号等多渠道。</p>
        </article>
        <article>
          <h3>AI 意图识别</h3>
          <p>10 层分层意图识别流水线：规则→关键词→向量召回→融合打分→LLM 精判，精准理解客户诉求。</p>
        </article>
        <article>
          <h3>置信度门控 Agent</h3>
          <p>高置信直接执行技能，中置信进入规划模式，低置信澄清追问，高风险转人工。成本可控、安全可审计。</p>
        </article>
        <article>
          <h3>RAG 知识检索</h3>
          <p>文档上传→自动解析分块→向量化→Qdrant 语义召回→Cross-Encoder 精排。精准命中知识库内容。</p>
        </article>
        <article>
          <h3>销售闭环</h3>
          <p>商品推荐→报价→创建订单→发货→签收，全流程在会话中完成。底价保护、订单快照、销售阶段自动推进。</p>
        </article>
        <article>
          <h3>SaaS 多租户</h3>
          <p>租户数据隔离、套餐订阅、RBAC 权限、LLM 模型池、用量统计、审计日志，平台级运维一目了然。</p>
        </article>
      </div>
    </section>

    <!-- ── 底部 ── -->
    <footer class="footer">
      <p>FastAgent &copy; 2026 — 基于 LangGraph + MCP + Skill 的智能客服平台</p>
    </footer>
  </div>
</template>

<style scoped>
.landing-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, #f5f7fa 0%, #e4ecf7 100%);
}
/* ── 顶部导航 ── */
.top-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 40px;
}
.logo {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: -0.5px;
}
.nav-links {
  display: flex;
  gap: 12px;
}
/* ── Hero 区 ── */
.hero {
  padding-bottom: 60px;
}
.hero-content {
  max-width: 720px;
  margin: 80px auto 0;
  text-align: center;
}
.hero-content h1 {
  font-size: 42px;
  font-weight: 800;
  color: var(--text-strong);
  line-height: 1.2;
  margin: 0;
}
.hero-sub {
  margin: 20px 0 32px;
  font-size: 17px;
  color: var(--text-muted);
  line-height: 1.7;
}
.hero-actions {
  display: flex;
  gap: 16px;
  justify-content: center;
}
/* ── 核心能力 ── */
.features {
  flex: 1;
  max-width: 1080px;
  margin: 0 auto;
  padding: 40px 24px 60px;
}
.features h2 {
  text-align: center;
  font-size: 28px;
  color: var(--text-strong);
  margin: 0 0 32px;
}
.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
}
.feature-grid article {
  padding: 24px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
}
.feature-grid h3 {
  margin: 0 0 10px;
  font-size: 17px;
  color: var(--text-strong);
}
.feature-grid p {
  margin: 0;
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.6;
}
/* ── 底部 ── */
.footer {
  text-align: center;
  padding: 30px 24px;
  border-top: 1px solid var(--border);
}
.footer p {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}
</style>
