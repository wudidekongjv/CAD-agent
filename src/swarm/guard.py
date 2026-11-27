"""Swarm 统一安全护栏

集中实现五项机制：
1. 安全门槛（SafetyGate）—— 操作分级、危险操作拦截、人工确认
2. 模型降级（ModelFallback）—— API 失败自动切本地，逐级降级
3. 数据校验（DataValidator）—— 参数校验、结果校验、元数据对比
4. 重试机制（RetryPolicy）—— 指数退避、错误分类、最大次数
5. 防死循环（LoopGuard）—— handoff 环检测、轮次上限、重复状态检测
"""

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ============ 1. 安全门槛 ============

class RiskLevel(Enum):
    LOW = "low"        # 查询类：drawing_info / layer_audit
    MEDIUM = "medium"  # 修改类：set_layer / add_dimension
    HIGH = "high"      # 破坏类：delete_entities / 覆盖原图


# 操作风险分级
OP_RISK = {
    "drawing_info": RiskLevel.LOW,
    "layer_audit": RiskLevel.LOW,
    "room_boundary": RiskLevel.LOW,
    "undo_checkpoint": RiskLevel.MEDIUM,
    "set_layer": RiskLevel.MEDIUM,
    "batch_modify": RiskLevel.MEDIUM,
    "draw_wall": RiskLevel.MEDIUM,
    "insert_block": RiskLevel.MEDIUM,
    "add_dimension": RiskLevel.MEDIUM,
    "offset": RiskLevel.MEDIUM,
    "hatch": RiskLevel.MEDIUM,
    "delete_entities": RiskLevel.HIGH,
}


@dataclass
class GateDecision:
    allowed: bool
    reason: str = ""
    requires_confirmation: bool = False
    risk: RiskLevel = RiskLevel.LOW


class SafetyGate:
    """安全门槛：拦截危险操作，要求人工确认"""

    def __init__(self, max_entities_per_op: int = 5000):
        self.max_entities_per_op = max_entities_per_op

    def check(self, ops: List[Dict], target_file: str,
              source_file: str, confirmed: bool = False) -> GateDecision:
        """检查一批操作的安全性"""
        for op in ops:
            name = op.get("op", "")
            risk = OP_RISK.get(name, RiskLevel.MEDIUM)

            # 硬拦截：禁止直接修改原图
            if target_file == source_file:
                return GateDecision(
                    False, "禁止在原始图纸上直接执行，必须使用临时副本", risk=RiskLevel.HIGH
                )

            # 高风险操作需人工确认
            if risk == RiskLevel.HIGH and not confirmed:
                return GateDecision(
                    False, f"高风险操作 {name} 需人工确认", True, RiskLevel.HIGH
                )

            # 批量操作实体数上限
            if name == "delete_entities":
                filter_expr = op.get("filter", "")
                if not filter_expr:
                    return GateDecision(False, "delete_entities 必须指定 filter", risk=RiskLevel.HIGH)

        return GateDecision(True, "通过", False, RiskLevel.LOW)


# ============ 2. 模型降级 ============

@dataclass
class FallbackResult:
    provider: str
    model: str
    success: bool
    error: str = ""


class ModelFallback:
    """模型降级链：deepseek → qwen → openai → local

    API 失败时自动尝试下一个，保证服务不中断。
    """

    CHAIN = ["deepseek", "qwen", "openai", "local"]

    def __init__(self, chain: Optional[List[str]] = None):
        self.chain = chain or self.CHAIN
        self.current_index = 0
        self.history: List[FallbackResult] = []

    def call(self, messages: List[Dict], tools: Optional[List[Dict]] = None,
             **kwargs) -> Tuple[Dict, str]:
        """按降级链调用模型，返回 (response, provider)"""
        from .llm import LLMClient

        errors = []
        for i in range(self.current_index, len(self.chain)):
            provider = self.chain[i]
            try:
                client = LLMClient(provider=provider)
                response = client.chat(messages, tools, **kwargs)
                self.current_index = i
                self.history.append(FallbackResult(provider, client.model, True))
                return response, provider
            except Exception as e:
                errors.append(f"{provider}: {e}")
                self.history.append(FallbackResult(provider, "", False, str(e)))
                continue

        raise RuntimeError(f"All model providers failed: {'; '.join(errors)}")

    def reset(self):
        """重置到首选模型"""
        self.current_index = 0


# ============ 3. 数据校验 ============

class DataValidator:
    """数据校验：参数、结构、结果三层"""

    REQUIRED_PARAMS = {
        "draw_wall": ["start", "end"],
        "insert_block": ["name", "insert"],
        "add_dimension": ["p1", "p2"],
        "delete_entities": ["filter"],
        "set_layer": ["layer", "props"],
        "batch_modify": ["filter", "props"],
    }

    def validate_ops(self, ops: List[Dict]) -> Tuple[bool, List[str]]:
        """校验操作参数完整性"""
        errors = []
        for i, op in enumerate(ops):
            name = op.get("op", "")
            required = self.REQUIRED_PARAMS.get(name, [])
            for p in required:
                if p not in op:
                    errors.append(f"op[{i}] {name} 缺少参数 {p}")
        return len(errors) == 0, errors

    def validate_result(self, before: Dict, after: Dict,
                        expected_ops: List[Dict]) -> Dict[str, Any]:
        """基于元数据对比校验结果"""
        from backend.metadata import compare_metadata

        diff = compare_metadata(before, after)
        expected_types = {op.get("op") for op in expected_ops}

        # 检查是否有实际变化
        has_change = bool(diff["added"] or diff["removed"] or diff["modified"])
        if expected_types and not has_change:
            return {
                "passed": False,
                "errors": ["执行后图纸无变化，可能操作未生效"],
                "diff": diff,
            }

        # 检查实体数量是否异常突变
        delta = abs(diff["entity_delta"])
        if delta > 500:
            return {
                "passed": False,
                "errors": [f"实体数量突变 {diff['entity_delta']}，疑似误操作"],
                "diff": diff,
            }

        return {"passed": True, "errors": [], "diff": diff}


# ============ 4. 重试机制 ============

@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    retryable_errors: tuple = ("timeout", "connection", "rate limit", "503", "502", "500")

    def should_retry(self, error: str, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        lower = error.lower()
        return any(k in lower for k in self.retryable_errors)

    def delay(self, attempt: int) -> float:
        """指数退避"""
        return min(self.base_delay * (2 ** attempt), self.max_delay)

    def execute(self, fn: Callable, *args, **kwargs) -> Tuple[Any, int]:
        """执行带重试的函数"""
        last_error = ""
        for attempt in range(self.max_attempts):
            try:
                return fn(*args, **kwargs), attempt + 1
            except Exception as e:
                last_error = str(e)
                if not self.should_retry(last_error, attempt):
                    break
                time.sleep(self.delay(attempt))
        raise RuntimeError(f"Failed after {attempt + 1} attempts: {last_error}")


# ============ 5. 防死循环 ============

class LoopGuard:
    """防死循环：handoff 环检测 + 重复状态检测 + 轮次上限"""

    def __init__(self, max_handoffs: int = 8, max_turns: int = 12):
        self.max_handoffs = max_handoffs
        self.max_turns = max_turns
        self.visited: List[str] = []
        self.state_hashes: Set[str] = set()
        self.count = 0

    def check_handoff(self, target: str, state: Dict) -> Tuple[bool, str]:
        """检查 handoff 是否形成环或超限"""
        self.count += 1
        self.visited.append(target)

        if self.count >= self.max_handoffs:
            return False, f"达到最大 handoff 次数 {self.max_handoffs}，强制终止"

        # 环检测：连续 A→B→A→B 三次以上
        if len(self.visited) >= 6:
            recent = self.visited[-6:]
            if recent[0] == recent[2] == recent[4] and recent[1] == recent[3] == recent[5]:
                return False, f"检测到 handoff 循环: {'→'.join(recent)}"

        # 重复状态检测（同一状态反复出现）
        state_str = str({
            "agent": state.get("current_agent", ""),
            "plan": str(state.get("plan", ""))[:200],
            "ops": str(state.get("generated_ops", ""))[:200],
        })
        h = hashlib.md5(state_str.encode()).hexdigest()
        if h in self.state_hashes:
            return False, "检测到重复状态，疑似死循环"
        self.state_hashes.add(h)

        return True, ""

    def check_turn(self, turn: int) -> bool:
        return turn < self.max_turns

    def reset(self):
        self.visited = []
        self.state_hashes.clear()
        self.count = 0
