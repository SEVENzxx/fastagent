"""分层意图识别流水线。

文件浏览器通常按字母排序，无法体现真实执行顺序；实际顺序以
`pipeline.py` 中的 `PIPELINE_STEPS` 和 `IntentRecognitionPipeline` 为准。

执行顺序：
1. normalizer.py         TextNormalizer 文本清洗
2. rule_matcher.py       RuleMatcher 强规则匹配
3. keyword_entity.py     KeywordEntityExtractor 关键词/实体识别
4. context_state.py      ContextStateResolver 会话状态/槽位补全
5. segmenter.py          MessageSegmenter 多问题拆句
6. vector_retriever.py   VectorIntentRetriever 向量候选召回
7. fusion_scorer.py      IntentFusionScorer 意图融合打分
8. ambiguity.py          AmbiguityDetector 歧义判断
9. llm_judge.py          LLMIntentJudge 低置信兜底
10. router.py            IntentRouter 最终路由
"""
