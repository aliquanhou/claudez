"""Intent Resonator — 从用户行为（光标、编辑、撤销）中蒸馏隐式意图。

v0.3.4 规则引擎：7 条规则覆盖 7 种意图信号。
0 LLM 依赖，纯数值信号处理。
"""

from __future__ import annotations

import json
import os
import time
import statistics
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class IntentSignal(Enum):
    EXPLORING = "exploring"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    IMPLEMENTING = "implementing"
    REVIEWING = "reviewing"
    STUCK = "stuck"
    CONFIDENT = "confident"


@dataclass
class BehavioralSnapshot:
    """行为快照 — 由 IDE 插件或模拟器提供。"""
    timestamp: float = 0.0
    cursor_speed: float = 0.0        # 字符/秒
    selection_length: int = 0
    chars_typed: int = 0
    deletions: int = 0
    undo_count: int = 0
    file_switches: int = 0
    scroll_speed: float = 0.0        # 行/秒
    idle_seconds: float = 0.0


@dataclass
class IntentVector:
    """从行为快照中解析出的意图向量。"""
    primary_intent: IntentSignal
    confidence: float                 # 0.0 – 1.0
    secondary_intents: list[tuple[IntentSignal, float]] = field(default_factory=list)
    urgency: float = 0.0              # 0.0 – 1.0
    narrative: str = ""


class IntentResonator:
    """意图共鸣器 — 从用户行为信号中蒸馏隐式意图。

    设计：
      - 保留最近 N 个快照，用滑动均值做决策
      - 7 条规则按优先级匹配（极端状态优先）
      - 置信度 = 特征值与阈值的归一化距离
    """

    # ── 规则阈值（经验值，后续可调整） ──

    # STUCK: 高撤销 + 高删除 + 停顿 + 无打字
    STUCK_DELETIONS_RATIO = 0.5       # 删除/打字 比例 > 50%
    STUCK_UNDO_MIN = 2                # 撤销次数 >= 2
    STUCK_IDLE_MIN = 10               # 空闲 >= 10s

    # EXPLORING: 高文件切换 + 高滚动 + 低打字
    EXPLORING_FILE_SWITCH_MIN = 3
    EXPLORING_SCROLL_MIN = 5
    EXPLORING_CHARS_MAX = 5

    # DEBUGGING: 中速光标 + 选择 + 删除 + 文件切换
    DEBUGGING_CURSOR_MIN = 5
    DEBUGGING_SELECTION_MIN = 10
    DEBUGGING_DELETIONS_MIN = 3

    # IMPLEMENTING: 高打字 + 高光标 + 低撤销
    IMPLEMENTING_CHARS_MIN = 15
    IMPLEMENTING_CURSOR_MIN = 15
    IMPLEMENTING_UNDO_MAX = 1

    # REFACTORING: 中打字 + 高删除 + 文件切换
    REFACTORING_CHARS_MIN = 5
    REFACTORING_DELETIONS_RATIO = 0.3
    REFACTORING_SWITCH_MIN = 2

    # REVIEWING: 高滚动 + 高选择 + 低打字
    REVIEWING_SCROLL_MIN = 8
    REVIEWING_SELECTION_MIN = 20
    REVIEWING_CHARS_MAX = 3

    # CONFIDENT: 高光标 + 低撤销 + 低空闲 + 低删除
    CONFIDENT_CURSOR_MIN = 25
    CONFIDENT_UNDO_MAX = 0.5
    CONFIDENT_IDLE_MAX = 3
    CONFIDENT_DELETIONS_RATIO = 0.1

    def __init__(self, window_size: int = 20, ttl_seconds: int = 300, max_history: int = 100) -> None:
        """初始化意图共鸣器。

        Args:
            window_size: 滑动窗口大小（参与评分的历史快照数）
            ttl_seconds: 快照 TTL 秒数（超过此时间的快照被自动淘汰）
            max_history: 历史快照最大数量（超过时 LRU 淘汰最旧）
        """
        self._window_size = window_size
        self._ttl_seconds = ttl_seconds
        self._max_history = max_history
        self._history: list[BehavioralSnapshot] = []

    # ── 公共接口 ──

    def _purge_expired(self) -> None:
        """清理超过 TTL 的过期快照。"""
        if self._ttl_seconds <= 0:
            return
        now = time.time()
        cutoff = now - self._ttl_seconds
        before = len(self._history)
        self._history = [s for s in self._history if s.timestamp >= cutoff]
        if len(self._history) < before:
            pass  # 静默清理

    def feed(self, snapshot: BehavioralSnapshot) -> None:
        """喂入一个行为快照。"""
        self._purge_expired()
        self._history.append(snapshot)
        # LRU 淘汰：超过 max_history 时移除最旧的
        while len(self._history) > self._max_history:
            self._history.pop(0)
        # 同时确保窗口大小不超限
        if len(self._history) > self._window_size:
            self._history = self._history[-self._window_size:]

    def get_intent(self) -> Optional[IntentVector]:
        """返回当前意图，数据不足时返回 None。"""
        self._purge_expired()
        if len(self._history) < 3:
            return None

        avg = self._compute_average()
        scores = self._evaluate_all(avg)
        if not scores:
            return None

        # 按分数排序，取最高分
        scores.sort(key=lambda x: x[1], reverse=True)
        primary, confidence = scores[0]
        secondaries = [(s, c) for s, c in scores[1:4] if c > 0.2]

        urgency = self._compute_urgency(primary, avg)
        narrative = self._build_narrative(primary, avg, confidence)

        return IntentVector(
            primary_intent=primary,
            confidence=min(confidence, 1.0),
            secondary_intents=secondaries,
            urgency=min(urgency, 1.0),
            narrative=narrative,
        )

    def reset(self) -> None:
        """清空历史，重置状态。"""
        self._history.clear()

    # ── 持久化接口 ──

    def persist(self, filepath: str) -> None:
        """将历史快照持久化到 JSON 文件。

        Args:
            filepath: 存储路径（.json）
        """
        try:
            dirname = os.path.dirname(filepath)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
            data = {
                "ttl_seconds": self._ttl_seconds,
                "max_history": self._max_history,
                "snapshots": [
                    {
                        "timestamp": s.timestamp,
                        "cursor_speed": s.cursor_speed,
                        "selection_length": s.selection_length,
                        "chars_typed": s.chars_typed,
                        "deletions": s.deletions,
                        "undo_count": s.undo_count,
                        "file_switches": s.file_switches,
                        "scroll_speed": s.scroll_speed,
                        "idle_seconds": s.idle_seconds,
                    }
                    for s in self._history
                ],
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            import logging
            logging.getLogger("claudez.cognition").warning(
                "intent_persist_error path=%s %s", filepath, e
            )

    def load(self, filepath: str) -> None:
        """从 JSON 文件加载历史快照。

        Args:
            filepath: 存储路径（.json）
        """
        try:
            if not os.path.exists(filepath):
                return
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("snapshots", [])
            self._history = [
                BehavioralSnapshot(
                    timestamp=s.get("timestamp", 0.0),
                    cursor_speed=s.get("cursor_speed", 0.0),
                    selection_length=s.get("selection_length", 0),
                    chars_typed=s.get("chars_typed", 0),
                    deletions=s.get("deletions", 0),
                    undo_count=s.get("undo_count", 0),
                    file_switches=s.get("file_switches", 0),
                    scroll_speed=s.get("scroll_speed", 0.0),
                    idle_seconds=s.get("idle_seconds", 0.0),
                )
                for s in raw
            ]
            self._purge_expired()
            # 应用 max_history 限制（从后往前保留最新的）
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            import logging
            logging.getLogger("claudez.cognition").info(
                "intent_load path=%s snapshots=%d ttl=%ds",
                filepath, len(self._history), self._ttl_seconds
            )
        except Exception as e:
            import logging
            logging.getLogger("claudez.cognition").warning(
                "intent_load_error path=%s %s", filepath, e
            )

    # ── 内部：滑动平均 ──

    def _compute_average(self) -> BehavioralSnapshot:
        """计算最近 N 个快照的均值。"""
        n = len(self._history)
        if n == 0:
            return BehavioralSnapshot()
        return BehavioralSnapshot(
            timestamp=self._history[-1].timestamp,
            cursor_speed=sum(s.cursor_speed for s in self._history) / n,
            selection_length=round(sum(s.selection_length for s in self._history) / n),
            chars_typed=round(sum(s.chars_typed for s in self._history) / n),
            deletions=round(sum(s.deletions for s in self._history) / n),
            undo_count=round(sum(s.undo_count for s in self._history) / n),
            file_switches=round(sum(s.file_switches for s in self._history) / n),
            scroll_speed=sum(s.scroll_speed for s in self._history) / n,
            idle_seconds=sum(s.idle_seconds for s in self._history) / n,
        )

    # ── 内部：规则引擎 ──

    def _evaluate_all(
        self, avg: BehavioralSnapshot,
    ) -> list[tuple[IntentSignal, float]]:
        """评估所有规则，返回 (信号, 置信度) 列表。"""
        results: list[tuple[IntentSignal, float]] = []

        # 优先级 1: STUCK — 极端状态优先
        stuck_score = self._score_stuck(avg)
        if stuck_score > 0.3:
            results.append((IntentSignal.STUCK, stuck_score))

        # 其他规则（按信息量降序：具体的排在通用前面）
        scores = [
            (IntentSignal.IMPLEMENTING, self._score_implementing(avg)),
            (IntentSignal.DEBUGGING, self._score_debugging(avg)),
            (IntentSignal.REFACTORING, self._score_refactoring(avg)),
            (IntentSignal.REVIEWING, self._score_reviewing(avg)),
            (IntentSignal.EXPLORING, self._score_exploring(avg)),
            (IntentSignal.CONFIDENT, self._score_confident(avg)),
        ]

        for signal, score in scores:
            if score > 0.2:
                results.append((signal, score))

        # 如果没有任何规则命中，最低置信度回归到 EXPLORING
        if not results:
            results.append((IntentSignal.EXPLORING, 0.15))

        return results

    def _score_stuck(self, avg: BehavioralSnapshot) -> float:
        """STUCK 检测：高撤销 + 高删除 + 停顿 + 无打字。"""
        total_chars = avg.chars_typed + avg.deletions
        deletion_ratio = avg.deletions / max(total_chars, 1)
        features = 0
        if deletion_ratio > self.STUCK_DELETIONS_RATIO:
            features += 1
        if avg.undo_count >= self.STUCK_UNDO_MIN:
            features += 1
        if avg.idle_seconds > self.STUCK_IDLE_MIN:
            features += 1
        if avg.chars_typed < 3:
            features += 1
        # 分数 = 命中特征数 / 4
        score = features / 4.0
        # 空闲时间加成
        idle_bonus = min(avg.idle_seconds / 60, 0.3)
        return min(score + idle_bonus, 1.0)

    def _score_exploring(self, avg: BehavioralSnapshot) -> float:
        """EXPLORING 检测：高文件切换 + 高滚动 + 低打字。"""
        features = 0
        if avg.file_switches >= self.EXPLORING_FILE_SWITCH_MIN:
            features += 1
        if avg.scroll_speed > self.EXPLORING_SCROLL_MIN:
            features += 1
        if avg.chars_typed <= self.EXPLORING_CHARS_MAX:
            features += 1
        return features / 3.0

    def _score_debugging(self, avg: BehavioralSnapshot) -> float:
        """DEBUGGING 检测：中速光标 + 选择 + 删除 + 文件切换。"""
        features = 0
        if avg.cursor_speed >= self.DEBUGGING_CURSOR_MIN:
            features += 1
        if avg.selection_length >= self.DEBUGGING_SELECTION_MIN:
            features += 1
        if avg.deletions >= self.DEBUGGING_DELETIONS_MIN:
            features += 1
        if avg.file_switches >= 1:
            features += 1
        return features / 4.0

    def _score_implementing(self, avg: BehavioralSnapshot) -> float:
        """IMPLEMENTING 检测：高打字 + 高光标 + 低撤销。"""
        features = 0
        if avg.chars_typed >= self.IMPLEMENTING_CHARS_MIN:
            features += 1
        if avg.cursor_speed >= self.IMPLEMENTING_CURSOR_MIN:
            features += 1
        if avg.undo_count <= self.IMPLEMENTING_UNDO_MAX:
            features += 1
        # 删除率低加分
        total = avg.chars_typed + avg.deletions
        if total > 0 and avg.deletions / total < 0.2:
            features += 1
        return features / 4.0

    def _score_refactoring(self, avg: BehavioralSnapshot) -> float:
        """REFACTORING 检测：中打字 + 高删除 + 文件切换。"""
        total = avg.chars_typed + avg.deletions
        deletion_ratio = avg.deletions / max(total, 1)
        features = 0
        if avg.chars_typed >= self.REFACTORING_CHARS_MIN:
            features += 1
        if deletion_ratio > self.REFACTORING_DELETIONS_RATIO:
            features += 1
        if avg.file_switches >= self.REFACTORING_SWITCH_MIN:
            features += 1
        if avg.undo_count >= 1:
            features += 1
        return features / 4.0

    def _score_reviewing(self, avg: BehavioralSnapshot) -> float:
        """REVIEWING 检测：高滚动 + 高选择 + 低打字。"""
        features = 0
        if avg.scroll_speed > self.REVIEWING_SCROLL_MIN:
            features += 1
        if avg.selection_length >= self.REVIEWING_SELECTION_MIN:
            features += 1
        if avg.chars_typed <= self.REVIEWING_CHARS_MAX:
            features += 1
        if avg.file_switches >= 1:
            features += 1
        return features / 4.0

    def _score_confident(self, avg: BehavioralSnapshot) -> float:
        """CONFIDENT 检测：高光标 + 低撤销 + 低空闲 + 低删除。"""
        total = avg.chars_typed + avg.deletions
        deletion_ratio = avg.deletions / max(total, 1)
        features = 0
        if avg.cursor_speed >= self.CONFIDENT_CURSOR_MIN:
            features += 1
        if avg.undo_count <= self.CONFIDENT_UNDO_MAX:
            features += 1
        if avg.idle_seconds < self.CONFIDENT_IDLE_MAX:
            features += 1
        if deletion_ratio < self.CONFIDENT_DELETIONS_RATIO:
            features += 1
        return features / 4.0

    # ── 内部：辅助 ──

    def _compute_urgency(
        self, signal: IntentSignal, avg: BehavioralSnapshot,
    ) -> float:
        """计算紧迫度。"""
        if signal == IntentSignal.STUCK:
            # 空闲越长越紧急
            return min(avg.idle_seconds / 30, 1.0)
        if signal == IntentSignal.CONFIDENT:
            return 0.1  # 自信 = 不急
        # 通用：基于 idle 的反比 + 文件切换节奏
        base = min(avg.file_switches / 10, 0.5)
        idle_factor = max(0, 1.0 - avg.idle_seconds / 20)
        return min(base + idle_factor * 0.3, 1.0)

    def _build_narrative(
        self, signal: IntentSignal, avg: BehavioralSnapshot, confidence: float,
    ) -> str:
        """生成人类可读的意图描述。"""
        templates = {
            IntentSignal.EXPLORING:
                f"正在探索代码库（{avg.file_switches} 次文件切换，{avg.scroll_speed:.0f} 行/秒滚动）",
            IntentSignal.DEBUGGING:
                f"正在调试（光标 {avg.cursor_speed:.0f} 字符/秒，选择 {avg.selection_length} 字符）",
            IntentSignal.REFACTORING:
                f"正在重构（{avg.deletions} 次删除，{avg.file_switches} 次文件切换）",
            IntentSignal.IMPLEMENTING:
                f"正在实现功能（{avg.chars_typed} 字符输入，{avg.cursor_speed:.0f} 字符/秒）",
            IntentSignal.REVIEWING:
                f"正在审查代码（{avg.scroll_speed:.0f} 行/秒滚动，选择 {avg.selection_length} 字符）",
            IntentSignal.STUCK:
                f"可能遇到困难（空闲 {avg.idle_seconds:.0f}s，{avg.undo_count} 次撤销）",
            IntentSignal.CONFIDENT:
                f"状态良好（光标 {avg.cursor_speed:.0f} 字符/秒，几乎无撤销）",
        }
        return templates.get(signal, f"意图识别: {signal.value} (置信度 {confidence:.0%})")
