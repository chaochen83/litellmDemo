from enum import Enum
from typing import Optional, List


class RoutingGoal(str, Enum):
    COST = "成本优先"
    LATENCY = "响应延迟优先"
    ACCURACY = "最大精度优先"
    COMPLIANCE = "合规隔离优先"


# 当前选路策略（可存 Redis/MySQL，这里内存演示）
_current_goal: Optional[RoutingGoal] = RoutingGoal.LATENCY


def get_routing_goal() -> RoutingGoal:
    return _current_goal or RoutingGoal.LATENCY


def set_routing_goal(goal: RoutingGoal) -> None:
    global _current_goal
    _current_goal = goal


# 各策略对应的模型列表（主模型 + fallback 顺序）。LiteLLM 使用 dashscope/、anthropic/ 等前缀
def get_models_for_goal(goal: RoutingGoal) -> List[str]:
    """
    成本优先：便宜模型优先（含 Claude Haiku、Qwen-Turbo）
    响应延迟优先：低延迟模型（含 Claude Haiku、Qwen-Turbo）
    最大精度优先：强模型优先（含 Claude Opus、Qwen-Max、GPT-4o）
    合规隔离优先：境内/合规模型（优先 Qwen，可选 Claude）
    """
    strategy_models = {
        RoutingGoal.COST: [
            "anthropic/claude-3-5-haiku-20241022",  # 便宜
            "dashscope/qwen-turbo",
            "gpt-3.5-turbo",
            "anthropic/claude-3-5-sonnet-20241022",
            "dashscope/qwen-plus",
            "gpt-4o-mini",
            "gpt-4o",
        ],
        RoutingGoal.LATENCY: [
            "anthropic/claude-3-5-haiku-20241022",  # 低延迟
            "dashscope/qwen-turbo",
            "gpt-3.5-turbo",
            "dashscope/qwen-plus",
            "gpt-4o-mini",
        ],
        RoutingGoal.ACCURACY: [
            "anthropic/claude-3-5-sonnet-20241022",
            "gpt-4o",
            "dashscope/qwen-max",
            "anthropic/claude-3-opus-20240229",
            "gpt-4-turbo",
            "dashscope/qwen-plus",
            "gpt-3.5-turbo",
        ],
        RoutingGoal.COMPLIANCE: [
            "dashscope/qwen-max",
            "dashscope/qwen-plus",
            "anthropic/claude-3-5-sonnet-20241022",
            "gpt-4o",
            "gpt-3.5-turbo",
        ],
    }
    return strategy_models.get(goal, ["claude-sonnet-4-20250514", "dashscope/qwen-turbo", "gpt-3.5-turbo"])
