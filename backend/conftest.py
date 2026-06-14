"""pytest 全局配置 — 在 graph 模块加载前设置测试模式。"""
import os

os.environ.setdefault("FASTAGENT_TEST_MODE", "1")
