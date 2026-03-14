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
    # model name要从这里面找：https://docs.litellm.ai/docs/providers/dashscope
    strategy_models = {
        # 目标：最低成本
        # 策略：选择各家中最便宜的轻量模型
        RoutingGoal.COST: [
            "claude-sonnet-4-20250514",           # Anthropic 最快、最便宜的模型
            "dashscope/qwen-turbo",                  # Qwen 的延迟优化/成本优化模型，正取代turbo
            "gpt-5-nano-2025-08-07",               # GPT 的轻量快速版本（假设名称，需确认）
        ],
        
        # 目标：最低延迟
        # 策略：选择各家中速度最快的模型，通常也是轻量模型
        RoutingGoal.LATENCY: [
            "claude-sonnet-4-20250514",           # Anthropic 速度最快的模型
            "dashscope/qwen-turbo",                  # Qwen 的延迟优化模型
            "gpt-5-nano-2025-08-07",               # GPT 的快速版本（假设名称，需确认）
        ],
        
        # 目标：最高准确度
        # 策略：选择各家的旗舰/最强模型
        RoutingGoal.ACCURACY: [
            "claude-opus-4.6",             # Anthropic 最智能、最强大的模型
            "gpt-5.4",                 # GPT 的旗舰版本（假设名称，需确认）
            "dashscope/qwen-max",                    # Qwen 的下一代旗舰模型
        ],
        
        # 目标：合规/安全
        # 策略：选择各家中合规性好、风格偏保守的模型。Qwen 在国内市场对合规有深度优化。
        #       根据一些报道，GPT-5.2 风格偏"冷"和安全 [citation:5]。
        RoutingGoal.COMPLIANCE: [
            "dashscope/qwen-max",                    # Qwen 旗舰，国内合规优化好
            "gpt-5.2",                      # GPT-5.2 本身已更注重安全 [citation:5]
            "claude-sonnet-4.6",            # Sonnet 作为主力，平衡性佳
        ],
    }
    return strategy_models.get(goal, ["claude-sonnet-4-20250514", "dashscope/qwen-turbo", "gpt-5.2-flash"])
