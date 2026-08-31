"""导出 benchmark 会话的完整学情 I/O 示例，与 data/io_examples/bm_TC-001_io.json 同结构。

输入画像(input_profile) 取自测试题真值 tests/test_cases_100.json 的 suitable_profile + expected_*，
经清晰枚举中文翻译后呈现；背景(background)保留基准原始输入值以保持诚实。
决策(decision_mid) 取自 task_metrics；产出(output_resources) 解析 task_resources 的
lecture/practice_guide/quiz/knowledge_refs JSON。

用法:
    python scripts/export_io_example.py bm_TC-001 bm_TC-020 bm_TC-048
输出:
    data/io_examples/<session_id>_io.json
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "wolegedou.db"
CASES = ROOT / "tests" / "test_cases_100.json"
OUT_DIR = ROOT / "data" / "io_examples"

KL = {"beginner": "入门", "intermediate": "中级", "advanced": "进阶"}
GOAL = {"learn_basics": "深入理解原理", "build_project": "项目落地",
        "quick_start": "快速上手应用", "algo_research": "算法研究"}
QT = {"concept": "概念理解", "operation": "操作步骤", "debugging": "调试排错",
      "architecture": "架构设计", "full_pipeline": "全链路规划"}
CPX = {"single_domain": "单领域", "cross_domain": "跨领域", "full_pipeline": "全链路"}


def _safe_json(text):
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _row(con, table, sid):
    cur = con.execute(f"SELECT * FROM {table} WHERE session_id = ?", (sid,))
    col = [d[0] for d in cur.description]
    r = cur.fetchone()
    return dict(zip(col, r)) if r else None


def build_io(sid):
    case_id = sid[len("bm_"):] if sid.startswith("bm_") else sid
    cases = json.load(open(CASES, encoding="utf-8"))["test_cases"]
    case = next((c for c in cases if c["id"] == case_id), None)
    if case is None:
        raise SystemExit(f"[SKIP] {sid}: 测试题 {case_id} 未找到")

    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    metrics = _row(con, "task_metrics", sid)
    resources = _row(con, "task_resources", sid)
    con.close()
    if metrics is None or resources is None:
        missing = [t for t, v in (("task_metrics", metrics),
                                   ("task_resources", resources)) if v is None]
        raise SystemExit(f"[SKIP] {sid} 缺少表: {missing}")

    sp = case.get("suitable_profile", {})
    domains = case.get("expected_domains", []) or []
    n_dom = len(domains)
    complexity = "单领域" if n_dom <= 1 else ("跨领域" if n_dom == 2 else "全链路")
    input_profile = {
        "session_id": sid,
        "version": 1,
        "knowledge_level": KL.get(sp.get("knowledge_level"), sp.get("knowledge_level")),
        "background": sp.get("background"),
        "current_goal": GOAL.get(sp.get("current_goal"), sp.get("current_goal")),
        "question_type": QT.get(case.get("expected_question_type"),
                                case.get("expected_question_type")),
        "domain_hint": json.dumps(domains, ensure_ascii=False),
        "complexity_estimate": complexity,
        "intent_type": "generation",
        "domain_confidence": json.dumps({d: "high" for d in domains},
                                        ensure_ascii=False),
        "created_at": metrics.get("created_at"),
        "test_results": None,
    }

    lecture = _safe_json(resources["lecture"]) or {}
    if "knowledge_refs_display" not in lecture:
        krefs = _safe_json(resources["knowledge_refs"]) or []
        lecture["knowledge_refs_display"] = [
            {"source": k.get("source"), "verification_status": k.get("verification_status")}
            for k in krefs
        ]
    output_resources = {
        "lecture": lecture,
        "practice_guide": _safe_json(resources["practice_guide"]) or {},
        "quiz": _safe_json(resources["quiz"]) or {},
        "knowledge_refs": _safe_json(resources["knowledge_refs"]) or [],
    }
    return {"session_id": sid, "input_profile": input_profile,
            "decision_mid": metrics, "output_resources": output_resources}


FAKE = ["create_agent", "claude-sonnet", "claude-opus", "gpt-5",
        "ImageLoader", "langchain_community.vectorstores.FAISS"]


def main():
    targets = sys.argv[1:] or ["bm_TC-001", "bm_TC-020", "bm_TC-048"]
    OUT_DIR.mkdir(exist_ok=True)
    for sid in targets:
        io = build_io(sid)
        out = OUT_DIR / f"{sid}_io.json"
        out.write_text(json.dumps(io, ensure_ascii=False, indent=2), encoding="utf-8")
        m = io["decision_mid"]
        blob = json.dumps(io["output_resources"], ensure_ascii=False)
        hits = [b for b in FAKE if b in blob]
        ip = io["input_profile"]
        print(f"[OK] {sid} -> {out.name}")
        print(f"     profile: {ip['knowledge_level']}/{ip['background']}/{ip['current_goal']} "
              f"| q={ip['question_type']} c={ip['complexity_estimate']} d={ip['domain_hint']}")
        print(f"     verdict={m['verdict']} override={m['override_reason']} "
              f"fa={m['fact_accuracy']} logic={m['logic_completeness']} "
              f"ped={m['pedagogical_fit']} trace={m['traceability_verified']}/{m['traceability_total']}")
        print(f"     fake_api_scan={hits if hits else 'clean'}")


if __name__ == "__main__":
    main()
