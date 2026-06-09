"""测试所有向量域的搜索能力，直接用真实 Qdrant，不 mock。"""

import asyncio
from app.ai.rag.vector_search import VectorDomain, VectorSearchService
from app.config import settings


async def _run_diagnostics():
    print(f"AI_EMBEDDING_ENABLED = {settings.AI_EMBEDDING_ENABLED}")
    print(f"QDRANT_ENABLED       = {settings.QDRANT_ENABLED}")
    print(f"QDRANT_URL           = {settings.QDRANT_URL}")

    if not settings.AI_EMBEDDING_ENABLED:
        print("❌ AI_EMBEDDING_ENABLED=False → search_text 第一行就 return []")
    if not settings.QDRANT_ENABLED:
        print("❌ QDRANT_ENABLED=False → search_text 第一行就 return []")

    # ── Qdrant 直连 ──
    print(f"\n── Qdrant 直连诊断 ──")
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{settings.QDRANT_URL}/collections"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                print(f"Qdrant 可用 ✅  集合列表: {[c['name'] for c in data.get('collections', [])]}")

                for coll in data.get("collections", []):
                    name = coll["name"]
                    try:
                        info_url = f"{settings.QDRANT_URL}/collections/{name}"
                        async with session.get(info_url, timeout=aiohttp.ClientTimeout(total=3)) as r2:
                            info = await r2.json()
                            print(f"  {name} → points_count={info.get('points_count', '?')}, "
                                  f"indexed_vectors_count={info.get('indexed_vectors_count', '?')}")
                    except Exception as e:
                        print(f"  {name} → 查询失败: {e}")
    except Exception as e:
        print(f"❌ Qdrant 连接失败: {e}")
        print(f"   确认 URL: {settings.QDRANT_URL}")

    # ── Embedding 诊断 ──
    print(f"\n── Embedding 诊断 ──")
    try:
        from app.integrations.embedding_client import EmbeddingClient
        ec = EmbeddingClient()
        vec = await ec.embed("测试文本")
        print(f"Embedding 可用 ✅ 维度={len(vec)}")
    except Exception as e:
        print(f"❌ Embedding 失败: {e}")


async def _run_search_all():
    vs = VectorSearchService()
    tenant_id = 319767484162940928  # 改成你实际用的 tenant_id

    queries = {
        VectorDomain.INTENT_SAMPLE: "咨询一下商品资料",
        VectorDomain.KNOWLEDGE_CHUNK: "咨询一下商品资料",
        VectorDomain.QA_PAIR: "能开发票吗",
        VectorDomain.PRODUCT: "咨询一下商品",
        VectorDomain.MARKETING_DOCUMENT: "促销活动",
        VectorDomain.IMAGE: "产品图片",
    }

    for domain, query in queries.items():
        print(f"\n{'=' * 60}")
        print(f"  域: {domain.value}  查询: {query}")
        try:
            hits = await vs.search_text(
                domain=domain,
                tenant_id=tenant_id,
                query=query,
                top_k=3,
            )
        except Exception as e:
            print(f"  错误: {e}")
            print(f"{'=' * 60}")
            continue
        print(f"  命中数: {len(hits)}")
        for i, h in enumerate(hits, 1):
            print(f"  [{i}] score={h.score:.4f}  payload={h.payload}")
        if not hits:
            print("  (无命中)")
    print()


def test_vector_diagnostics():
    """诊断 Qdrant + Embedding 连接和配置。"""
    asyncio.run(_run_diagnostics())


def test_search_all_domains():
    """6 个向量域逐一检索，打印命中结果。"""
    asyncio.run(_run_search_all())


if __name__ == "__main__":
    asyncio.run(_run_diagnostics())
    asyncio.run(_run_search_all())


