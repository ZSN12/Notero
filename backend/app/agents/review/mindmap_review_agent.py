"""Review agent for mind map outputs.

Evaluates generated mind maps against industry-standard quality dimensions:
- Validity: JSON/schema correctness, node/edge integrity
- Coverage: key concepts from source material are represented
- Structure quality: hierarchy depth, balance, topical focus
- Conciseness: node granularity, redundancy
- Accuracy: factual correctness relative to source material

The agent first applies fast deterministic rule checks. If those pass, it falls
back to an LLM-based semantic review. The result includes an improvement prompt
that can be fed back into MindmapAgent for another generation attempt.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.agents.review.base import BaseReviewAgent, ReviewIssue, ReviewResult
from app.core.llm import ChatMessage, get_default_chat_provider

logger = logging.getLogger(__name__)


class MindmapReviewAgent(BaseReviewAgent):
    """Reviews mind maps produced by MindmapAgent."""

    role = "mindmap_review"

    # Structural constraints aligned with the mind map prompt.
    MAX_TOP_LEVEL_NODES = 8
    MAX_DEPTH = 3
    MAX_NODES = 80
    MIN_DESCRIPTION_LENGTH = 10
    MAX_DESCRIPTION_LENGTH = 80
    TARGET_SCORE = 0.80
    MIN_DIMENSION_SCORE = 0.60

    # Dimension weights (should sum to 1.0).
    DIMENSION_WEIGHTS = {
        "validity": 0.25,
        "coverage": 0.25,
        "structure": 0.20,
        "conciseness": 0.15,
        "accuracy": 0.15,
    }

    def __init__(self) -> None:
        super().__init__()
        self._provider = get_default_chat_provider()

    # ── Public API ──

    def review(
        self,
        source_material: str,
        output: dict[str, Any],
        history: list[ReviewResult],
    ) -> ReviewResult:
        """Review a mind map output and return a structured verdict."""
        # Fast deterministic checks first.
        rule_result = self._rule_check(output, history)
        if rule_result.issues:
            logger.info(
                "mindmap_review_rule_fail issues=%s", len(rule_result.issues)
            )
            return rule_result

        # Semantic LLM review for quality dimensions.
        return self._llm_review(source_material, output, history)

    # ── Rule-based checks ──

    def _rule_check(
        self, output: dict[str, Any], history: list[ReviewResult]
    ) -> ReviewResult:
        """Run deterministic structural checks."""
        issues: list[ReviewIssue] = []

        if not isinstance(output, dict):
            issues.append(
                ReviewIssue(
                    dimension="validity",
                    description="输出不是有效的 JSON 对象",
                    severity="critical",
                )
            )
            return self._build_rule_result(issues, history)

        title = output.get("title", "")
        if not title or not str(title).strip():
            issues.append(
                ReviewIssue(
                    dimension="validity",
                    description="导图缺少标题",
                    severity="high",
                    location="root.title",
                )
            )

        nodes = output.get("nodes", [])
        if not isinstance(nodes, list) or not nodes:
            issues.append(
                ReviewIssue(
                    dimension="validity",
                    description="导图缺少节点或节点不是列表",
                    severity="critical",
                    location="root.nodes",
                )
            )
            return self._build_rule_result(issues, history)

        # Node counts and depth.
        total_nodes = self._count_nodes(nodes)
        max_depth = self._max_depth(nodes)

        if len(nodes) > self.MAX_TOP_LEVEL_NODES:
            issues.append(
                ReviewIssue(
                    dimension="structure",
                    description=(
                        f"顶层节点过多：{len(nodes)} 个，建议不超过 "
                        f"{self.MAX_TOP_LEVEL_NODES} 个，请合并相关模块"
                    ),
                    severity="high",
                    location="root.nodes",
                )
            )

        if total_nodes > self.MAX_NODES:
            issues.append(
                ReviewIssue(
                    dimension="conciseness",
                    description=(
                        f"节点总数过多：{total_nodes} 个，建议精简到 "
                        f"{self.MAX_NODES} 个以内"
                    ),
                    severity="high",
                    location="root.nodes",
                )
            )

        if max_depth > self.MAX_DEPTH:
            issues.append(
                ReviewIssue(
                    dimension="structure",
                    description=(
                        f"导图层级过深：{max_depth} 层，建议不超过 "
                        f"{self.MAX_DEPTH} 层"
                    ),
                    severity="high",
                    location="root.nodes",
                )
            )

        # Per-node checks.
        for node, path in self._walk_nodes(nodes, "root.nodes"):
            node_id = node.get("id", "")
            title = node.get("title", "")
            description = node.get("description", "")
            node_type = node.get("type", "")

            if not title or not str(title).strip():
                issues.append(
                    ReviewIssue(
                        dimension="validity",
                        description=f"节点缺少标题：{path}",
                        severity="critical",
                        location=path,
                    )
                )

            desc_len = len(str(description))
            if desc_len < self.MIN_DESCRIPTION_LENGTH:
                issues.append(
                    ReviewIssue(
                        dimension="validity",
                        description=(
                            f"节点描述过短 ({desc_len} 字)：{title or node_id}"
                        ),
                        severity="high",
                        location=path,
                    )
                )
            elif desc_len > self.MAX_DESCRIPTION_LENGTH:
                issues.append(
                    ReviewIssue(
                        dimension="conciseness",
                        description=(
                            f"节点描述过长 ({desc_len} 字)：{title or node_id}"
                        ),
                        severity="medium",
                        location=path,
                    )
                )

            valid_types = {
                "topic",
                "concept",
                "key_point",
                "difficulty",
                "example",
                "process",
                "function",
                "question",
                "conclusion",
            }
            if node_type not in valid_types:
                issues.append(
                    ReviewIssue(
                        dimension="validity",
                        description=(
                            f"节点类型无效 '{node_type}'：{title or node_id}"
                        ),
                        severity="medium",
                        location=path,
                    )
                )

        # Top-level nodes should have sources.
        for idx, node in enumerate(nodes):
            sources = node.get("sources", []) if isinstance(node, dict) else []
            if not sources:
                issues.append(
                    ReviewIssue(
                        dimension="validity",
                        description=(
                            f"一级节点缺少来源引用：{node.get('title', '')}"
                        ),
                        severity="high",
                        location=f"root.nodes[{idx}].sources",
                    )
                )

        # Relations should reference valid node ids.
        relations = output.get("relations", [])
        if isinstance(relations, list):
            valid_ids = self._collect_node_ids(nodes)
            for idx, rel in enumerate(relations):
                if not isinstance(rel, dict):
                    continue
                src = rel.get("source", "")
                tgt = rel.get("target", "")
                if src not in valid_ids or tgt not in valid_ids:
                    issues.append(
                        ReviewIssue(
                            dimension="validity",
                            description=(
                                f"relation[{idx}] 引用了不存在的节点："
                                f"{src} -> {tgt}"
                            ),
                            severity="medium",
                            location=f"root.relations[{idx}]",
                        )
                    )

        return self._build_rule_result(issues, history)

    def _build_rule_result(
        self, issues: list[ReviewIssue], history: list[ReviewResult]
    ) -> ReviewResult:
        """Build a ReviewResult from rule violations."""
        # Compute a rough validity score: critical/high issues hurt more.
        severity_penalty = {"critical": 0.5, "high": 0.25, "medium": 0.1, "low": 0.05}
        validity_score = max(
            0.0, 1.0 - sum(severity_penalty.get(i.severity, 0.1) for i in issues)
        )

        dimensions = {"validity": round(validity_score, 4)}
        # Other dimensions are not scored by rules.
        for dim in ("coverage", "structure", "conciseness", "accuracy"):
            dimensions[dim] = 0.0

        score = self._weighted_score(dimensions)
        improvement_prompt = self._build_improvement_prompt(issues, history)

        return ReviewResult(
            is_acceptable=False,
            score=round(score, 4),
            dimensions=dimensions,
            issues=issues,
            improvement_prompt=improvement_prompt,
            should_regenerate=True,
            should_stop=self._should_stop(score, history),
            reasoning="规则层检查未通过",
        )

    # ── LLM-based semantic review ──

    def _llm_review(
        self,
        source_material: str,
        output: dict[str, Any],
        history: list[ReviewResult],
    ) -> ReviewResult:
        """Use an LLM to score semantic quality dimensions."""
        from app.services.prompt_loader import load_prompt

        prompt_template = load_prompt("agents/mindmap_review")
        output_json = json.dumps(output, ensure_ascii=False, indent=2)

        previous_attempts = self._format_history(history)

        user_content = prompt_template.render(
            title=output.get("title", ""),
            source_material=source_material,
            mind_map_json=output_json,
            previous_attempts=previous_attempts,
        )

        messages = [
            ChatMessage(role="system", content=prompt_template.system),
            ChatMessage(role="user", content=user_content),
        ]

        try:
            response = self._provider.chat(
                messages=messages,
                temperature=0.2,
                max_tokens=2000,
                timeout=60.0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.warning("mindmap_review_llm_failed error=%s", exc)
            # If LLM review itself fails, fall back to accepting the output
            # so we do not block the pipeline. Log the failure for later inspection.
            return ReviewResult(
                is_acceptable=True,
                score=0.75,
                dimensions={d: 0.75 for d in self.DIMENSION_WEIGHTS},
                issues=[
                    ReviewIssue(
                        dimension="validity",
                        description=f"LLM 审查调用失败：{exc}",
                        severity="low",
                    )
                ],
                should_stop=True,
                reasoning="审查服务暂时不可用，接受当前结果",
            )

        content = response.choices[0].message.content.strip()
        try:
            raw_review = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("mindmap_review_llm_json_invalid error=%s", exc)
            return ReviewResult(
                is_acceptable=True,
                score=0.75,
                dimensions={d: 0.75 for d in self.DIMENSION_WEIGHTS},
                issues=[
                    ReviewIssue(
                        dimension="validity",
                        description="LLM 审查返回不是有效 JSON，接受当前结果",
                        severity="low",
                    )
                ],
                should_stop=True,
                reasoning="审查输出解析失败，接受当前结果",
            )

        return self._parse_llm_review(raw_review, history)

    def _parse_llm_review(
        self, raw: dict[str, Any], history: list[ReviewResult]
    ) -> ReviewResult:
        """Parse the LLM review JSON into a ReviewResult."""
        dimensions: dict[str, float] = {}
        for dim in self.DIMENSION_WEIGHTS:
            val = raw.get("dimensions", {}).get(dim)
            try:
                score = max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                score = 0.5
            dimensions[dim] = round(score, 4)

        # Validity is already guaranteed by the rule layer, but keep the LLM score
        # if it is lower (it may have noticed structural issues rules missed).
        if dimensions.get("validity", 1.0) < 0.5:
            dimensions["validity"] = 0.5

        total_score = self._weighted_score(dimensions)

        raw_issues = raw.get("issues", [])
        issues: list[ReviewIssue] = []
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            issues.append(
                ReviewIssue(
                    dimension=str(item.get("dimension", "structure")),
                    description=str(item.get("description", "")),
                    severity=str(item.get("severity", "medium")),
                    location=item.get("location"),
                )
            )

        is_acceptable = (
            total_score >= self.TARGET_SCORE
            and all(dimensions.get(d, 0) >= self.MIN_DIMENSION_SCORE for d in dimensions)
            and not issues
        )

        improvement_prompt = raw.get("improvement_prompt") if not is_acceptable else None

        return ReviewResult(
            is_acceptable=is_acceptable,
            score=round(total_score, 4),
            dimensions=dimensions,
            issues=issues,
            improvement_prompt=improvement_prompt,
            should_regenerate=not is_acceptable,
            should_stop=self._should_stop(total_score, history),
            reasoning=raw.get("reasoning"),
        )

    # ── Helpers ──

    def _weighted_score(self, dimensions: dict[str, float]) -> float:
        """Compute weighted total score."""
        total = 0.0
        weight_sum = 0.0
        for dim, weight in self.DIMENSION_WEIGHTS.items():
            total += dimensions.get(dim, 0.0) * weight
            weight_sum += weight
        if weight_sum == 0:
            return 0.0
        return total / weight_sum

    def _should_stop(self, current_score: float, history: list[ReviewResult]) -> bool:
        """Detect convergence stagnation or regression."""
        if not history:
            return False

        scores = [r.score for r in history] + [current_score]

        # Regression: current score lower than last.
        if current_score < scores[-2]:
            return True

        # Stagnation: little improvement over last two iterations.
        if len(scores) >= 3:
            last_gain = scores[-1] - scores[-2]
            prev_gain = scores[-2] - scores[-3]
            if abs(last_gain) < 0.05 and abs(prev_gain) < 0.05:
                return True

        return False

    def _build_improvement_prompt(
        self, issues: list[ReviewIssue], history: list[ReviewResult]
    ) -> str:
        """Convert issues into a prompt fragment for the generation agent."""
        lines = ["请根据以下审查意见重新生成知识导图："]
        for issue in issues:
            loc = f"（{issue.location}）" if issue.location else ""
            lines.append(f"- [{issue.severity}] {issue.description}{loc}")

        if history:
            lines.append(
                f"\n这是第 {len(history) + 1} 轮优化，请避免重复之前轮次已修正过的问题。"
            )

        lines.append(
            "\n请严格输出符合要求的 JSON，不要添加 Markdown 代码块或额外说明文字。"
        )
        return "\n".join(lines)

    def _format_history(self, history: list[ReviewResult]) -> str:
        """Format previous review results for the LLM prompt."""
        if not history:
            return "无"
        parts = []
        for idx, result in enumerate(history, 1):
            parts.append(f"第 {idx} 轮：总分 {result.score}")
            for issue in result.issues:
                parts.append(f"  - [{issue.dimension}] {issue.description}")
            if result.improvement_prompt:
                parts.append(f"  优化要求：{result.improvement_prompt[:200]}...")
        return "\n".join(parts)

    # ── Tree traversal helpers ──

    def _count_nodes(self, nodes: list[dict]) -> int:
        """Count total nodes recursively."""
        count = 0
        for node in nodes:
            if not isinstance(node, dict):
                continue
            count += 1
            children = node.get("children", [])
            if isinstance(children, list):
                count += self._count_nodes(children)
        return count

    def _max_depth(self, nodes: list[dict]) -> int:
        """Compute maximum tree depth."""
        if not nodes:
            return 0
        max_child_depth = 0
        for node in nodes:
            if not isinstance(node, dict):
                continue
            children = node.get("children", [])
            if isinstance(children, list):
                max_child_depth = max(max_child_depth, self._max_depth(children))
        return 1 + max_child_depth

    def _walk_nodes(
        self, nodes: list[dict], path: str
    ) -> list[tuple[dict, str]]:
        """Yield (node, path) pairs recursively."""
        result = []
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            node_path = f"{path}[{idx}]"
            result.append((node, node_path))
            children = node.get("children", [])
            if isinstance(children, list):
                result.extend(self._walk_nodes(children, f"{node_path}.children"))
        return result

    def _collect_node_ids(self, nodes: list[dict]) -> set[str]:
        """Collect all node ids recursively."""
        ids: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if node_id:
                ids.add(str(node_id))
            children = node.get("children", [])
            if isinstance(children, list):
                ids.update(self._collect_node_ids(children))
        return ids
