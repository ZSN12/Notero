"""Normalization helpers shared by agent implementations and legacy services.

Moving these here avoids circular imports between agents/ and services/.
"""

from __future__ import annotations

from typing import Optional


# ── Mind map normalization ──

VALID_NODE_TYPES = {"topic", "concept", "key_point", "difficulty", "example", "process", "function", "question", "conclusion"}
DEFAULT_NODE_TYPE = "concept"
VALID_IMPORTANCE = {"high", "medium", "low"}
DEFAULT_IMPORTANCE = "medium"
VALID_RELATION_TYPES = {"contrast", "step", "example_of", "used_by", "depends_on", "warning", "related"}
DEFAULT_RELATION_TYPE = "related"
RESERVED_NODE_IDS = {"root"}
RELATION_LABELS = {
    "contrast": "对比",
    "step": "步骤",
    "example_of": "示例",
    "used_by": "被使用",
    "depends_on": "依赖",
    "warning": "注意",
    "related": "相关",
}


def normalize_mind_map_sources(sources) -> list[dict]:
    """Ensure sources is a list of dicts with required fields."""
    if not isinstance(sources, list):
        return []
    result = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        source_type = s.get("source_type", "")
        if source_type not in ("transcript", "note", "ppt"):
            source_type = "note"
        snippet = str(s.get("snippet", ""))
        page = s.get("page") if isinstance(s.get("page"), int) else None
        block_id = str(s.get("block_id", "")) if s.get("block_id") else None
        result.append({
            "source_type": source_type,
            "snippet": snippet,
            "page": page,
            "block_id": block_id,
        })
    return result


def normalize_mind_map_node(node: dict) -> Optional[dict]:
    """Normalize a single node: fill defaults, discard if missing required fields."""
    if not isinstance(node, dict):
        return None

    node_id = node.get("id")
    title = node.get("title")
    if not node_id or not title:
        return None

    node_type = node.get("type", DEFAULT_NODE_TYPE)
    if node_type not in VALID_NODE_TYPES:
        node_type = DEFAULT_NODE_TYPE

    importance = node.get("importance", DEFAULT_IMPORTANCE)
    if importance not in VALID_IMPORTANCE:
        importance = DEFAULT_IMPORTANCE

    return {
        "id": str(node_id),
        "title": str(title),
        "description": str(node.get("description", "")),
        "type": node_type,
        "importance": importance,
        "sources": normalize_mind_map_sources(node.get("sources", [])),
        "children": normalize_mind_map_nodes(node.get("children", [])),
    }


def normalize_mind_map_nodes(nodes) -> list[dict]:
    """Normalize a list of nodes, dropping invalid ones."""
    if not isinstance(nodes, list):
        return []
    result = []
    for n in nodes:
        normalized = normalize_mind_map_node(n)
        if normalized:
            result.append(normalized)
    return result


def _collect_all_node_ids(nodes: list) -> set[str]:
    """Recursively collect all node ids from the tree."""
    ids: set[str] = set()
    for n in nodes:
        if isinstance(n, dict):
            node_id = n.get("id")
            if node_id:
                ids.add(str(node_id))
            children = n.get("children", [])
            if isinstance(children, list):
                ids.update(_collect_all_node_ids(children))
    return ids


def _remap_reserved_ids(nodes: list, id_remap: dict[str, str], counter: list[int]) -> None:
    for n in nodes:
        if not isinstance(n, dict):
            continue
        node_id = n.get("id")
        if node_id in RESERVED_NODE_IDS:
            new_id = f"node-root-{counter[0]}"
            counter[0] += 1
            id_remap[str(node_id)] = new_id
            n["id"] = new_id
        children = n.get("children", [])
        if isinstance(children, list):
            _remap_reserved_ids(children, id_remap, counter)


def normalize_mind_map_relations(raw_relations, valid_node_ids: set[str]) -> list[dict]:
    """Normalize relations, discarding invalid ones."""
    if not isinstance(raw_relations, list):
        return []
    result = []
    for r in raw_relations:
        if not isinstance(r, dict):
            continue
        source = str(r.get("source", ""))
        target = str(r.get("target", ""))
        if not source or not target:
            continue
        if source not in valid_node_ids or target not in valid_node_ids:
            continue
        rel_type = r.get("type", DEFAULT_RELATION_TYPE)
        if rel_type not in VALID_RELATION_TYPES:
            rel_type = DEFAULT_RELATION_TYPE
        label = r.get("label", "")
        if not label:
            label = RELATION_LABELS.get(rel_type, "相关")
        result.append({
            "source": source,
            "target": target,
            "type": rel_type,
            "label": str(label),
        })
    return result


def normalize_mind_map_data(data: dict) -> dict:
    """Normalize and validate the entire mind map data structure.

    - Ensures nodes is a list, discarding invalid nodes.
    - Fills defaults for missing fields.
    - Recursively normalizes children.
    - Normalizes relations, discarding invalid ones.
    - Raises ValueError if the result is unusable (no valid nodes).
    """
    if not isinstance(data, dict):
        raise ValueError("AI 返回的 JSON 不是对象")

    raw_nodes = data.get("nodes", [])

    # Remap reserved ids before normalization
    id_remap: dict[str, str] = {}
    _remap_reserved_ids(raw_nodes, id_remap, [0])

    if id_remap and isinstance(data.get("relations"), list):
        for r in data["relations"]:
            if isinstance(r, dict):
                if r.get("source") in id_remap:
                    r["source"] = id_remap[r["source"]]
                if r.get("target") in id_remap:
                    r["target"] = id_remap[r["target"]]

    nodes = normalize_mind_map_nodes(raw_nodes)
    if not nodes:
        raise ValueError("AI 返回的 JSON 中没有有效的节点")

    valid_ids = _collect_all_node_ids(raw_nodes)
    raw_relations = data.get("relations", [])
    relations = normalize_mind_map_relations(raw_relations, valid_ids)

    raw_title = data.get("title", "知识导图")
    return {
        "title": str(raw_title) if raw_title else "知识导图",
        "summary": str(data.get("summary", "")),
        "nodes": nodes,
        "relations": relations,
    }


# ── Quiz normalization ──

VALID_OPTION_IDS = {"A", "B", "C", "D"}
VALID_QUESTION_SOURCE_TYPES = {"transcript", "note", "ppt"}
VALID_QUESTION_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_QUESTION_TYPES = {"diagnostic", "review", "variant"}


def normalize_quiz_option(option: dict) -> Optional[dict]:
    if not isinstance(option, dict):
        return None
    opt_id = option.get("id")
    text = option.get("text")
    if not opt_id or not text:
        return None
    opt_id = str(opt_id).upper()
    if opt_id not in VALID_OPTION_IDS:
        return None
    return {
        "id": opt_id,
        "text": str(text),
        "explanation": str(option.get("explanation", "")),
    }


def normalize_quiz_question(question: dict) -> Optional[dict]:
    if not isinstance(question, dict):
        return None
    q_id = question.get("id")
    q_text = question.get("question")
    if not q_id or not q_text:
        return None

    raw_options = question.get("options", [])
    if not isinstance(raw_options, list):
        return None

    options = []
    for opt in raw_options:
        normalized = normalize_quiz_option(opt)
        if normalized:
            options.append(normalized)

    if len(options) != 4:
        return None
    option_ids = {o["id"] for o in options}
    if option_ids != VALID_OPTION_IDS:
        return None

    answer = str(question.get("answer", "")).upper()
    if answer not in option_ids:
        return None

    raw_source = question.get("source", {})
    if not isinstance(raw_source, dict):
        raw_source = {}
    source_type = raw_source.get("source_type", "note")
    if source_type not in VALID_QUESTION_SOURCE_TYPES:
        source_type = "note"
    page = raw_source.get("page")
    if not isinstance(page, int):
        page = None

    raw_points = question.get("knowledge_points", [])
    knowledge_points: list[str] = []
    if isinstance(raw_points, list):
        for point in raw_points:
            point_text = str(point).strip()
            if point_text and point_text not in knowledge_points:
                knowledge_points.append(point_text[:40])
    if not knowledge_points:
        fallback = str(raw_source.get("snippet", "") or q_text).strip()
        knowledge_points = [fallback[:24] or "本节课核心知识"]

    difficulty = str(question.get("difficulty", "medium")).lower()
    if difficulty not in VALID_QUESTION_DIFFICULTIES:
        difficulty = "medium"

    question_type = str(question.get("question_type", "diagnostic")).lower()
    if question_type not in VALID_QUESTION_TYPES:
        question_type = "diagnostic"

    source_question_id = question.get("source_question_id")
    source_question_id = str(source_question_id) if source_question_id else None

    return {
        "id": str(q_id),
        "question": str(q_text),
        "options": options,
        "answer": answer,
        "explanation": str(question.get("explanation", "")),
        "knowledge_points": knowledge_points,
        "difficulty": difficulty,
        "question_type": question_type,
        "source_question_id": source_question_id,
        "source": {
            "source_type": source_type,
            "snippet": str(raw_source.get("snippet", "")),
            "page": page,
        },
    }


def normalize_quiz_data(data: dict) -> dict:
    """Normalize and validate the quiz bank data structure."""
    if not isinstance(data, dict):
        raise ValueError("AI 返回的 JSON 不是对象")

    raw_questions = data.get("questions", [])
    if not isinstance(raw_questions, list):
        raise ValueError("AI 返回的 JSON 中 questions 不是列表")

    questions = []
    for q in raw_questions:
        normalized = normalize_quiz_question(q)
        if normalized:
            questions.append(normalized)

    if not questions:
        raise ValueError("AI 返回的 JSON 中没有有效的题目")

    return {
        "title": str(data.get("title", "本节课测验")),
        "questions": questions,
    }
