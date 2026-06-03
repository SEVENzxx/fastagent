"""Phase 9 Agent — 置信度门控混合架构。

执行路径：
  RoutedIntent → build_context → decide_execution_mode → plan_tools
  → dispatch_tools → generate_reply → post_process → final_reply
"""

from app.ai.agent.graph import run_agent

__all__ = ["run_agent"]
