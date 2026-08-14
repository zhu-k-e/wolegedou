"""导出 ≥3 组差异化学习者学情 I/O 示例（赛题提交硬要求）。

从 benchmark(bm_) 会话中抽取：
  - 输入画像：student_profiles（学情诊断 Agent 的输入特征）
  - 中间决策：task_metrics（审核裁判 Agent 的 verdict / 溯源核验 / 质量分）
  - 最终资源：task_resources（领域生成 Agent 输出的讲义/练习/测验/知识引用）

零重跑：直接读现有 bm_ 数据库，不涉及任何生成 / 评判代码改动。
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "wolegedou.db"
OUT = ROOT / "data" / "io_examples"
OUT.mkdir(parents=True, exist_ok=True)


def _load_json(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def main():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row

    sessions = [r["session_id"] for r in c.execute(
        "SELECT DISTINCT session_id FROM task_resources WHERE session_id LIKE 'bm_%' ORDER BY session_id"
    )]
    examples = []
    for sid in sessions:
        prof = c.execute(
            "SELECT * FROM student_profiles WHERE session_id=? ORDER BY version DESC LIMIT 1", (sid,)
        ).fetchone()
        metrics = c.execute(
            "SELECT * FROM task_metrics WHERE session_id=? ORDER BY id DESC LIMIT 1", (sid,)
        ).fetchone()
        res = c.execute(
            "SELECT lecture, practice_guide, quiz, knowledge_refs FROM task_resources WHERE session_id=?", (sid,)
        ).fetchone()
        if not (prof and metrics and res):
            continue
        examples.append({
            "session_id": sid,
            "input_profile": {k: prof[k] for k in prof.keys()},
            "decision_mid": {k: metrics[k] for k in metrics.keys()},
            "output_resources": {
                "lecture": _load_json(res["lecture"]),
                "practice_guide": _load_json(res["practice_guide"]),
                "quiz": _load_json(res["quiz"]),
                "knowledge_refs": _load_json(res["knowledge_refs"]),
            },
        })
    c.close()

    # 选 3 组差异化（优先按 knowledge_level 区分，其次 domain_hint）
    by_level = {}
    for ex in examples:
        lvl = (ex["input_profile"].get("knowledge_level") or "未知")
        by_level.setdefault(lvl, []).append(ex)
    chosen = []
    for lvl, lst in by_level.items():
        if len(chosen) >= 3:
            break
        chosen.append(lst[0])

    if len(chosen) < 3:
        seen = {c["session_id"] for c in chosen}
        for ex in examples:
            if len(chosen) >= 3:
                break
            if ex["session_id"] in seen:
                continue
            dom = (ex["input_profile"].get("domain_hint") or "")
            if any(dom == (c["input_profile"].get("domain_hint") or "") for c in chosen):
                continue
            chosen.append(ex)
            seen.add(ex["session_id"])

    for ex in examples:
        if len(chosen) >= 3:
            break
        if ex["session_id"] not in {c["session_id"] for c in chosen}:
            chosen.append(ex)

    readme = [
        "# 差异化学情 I/O 示例（≥3 组）",
        "",
        "赛题提交硬要求：差异化学习者初始学情数据源，须含「输入画像特征 + 多智能体协同决策中间数据 + 最终生成的个性化学习资源」完整 I/O。",
        "数据来源：benchmark(`bm_`) 会话真实落库，零重跑导出。每个示例另存为 `<session_id>_io.json`（完整 JSON）。",
        "",
        f"本批导出 **{len(chosen)}** 组。",
        "",
    ]
    for i, ex in enumerate(chosen, 1):
        sid = ex["session_id"]
        p = ex["input_profile"]
        d = ex["decision_mid"]
        out = ex["output_resources"]
        lec = out["lecture"]
        lec_txt = (lec.get("conclusion") if isinstance(lec, dict) else str(lec)) or ""
        readme += [
            f"## 示例 {i} — {sid}",
            "",
            f"- **输入画像（学情诊断 Agent）**：知识水平={p.get('knowledge_level')} ｜ 背景={p.get('background')} ｜ 领域提示={p.get('domain_hint')} ｜ 复杂度估计={p.get('complexity_estimate')} ｜ 目标={p.get('current_goal')} ｜ 题型={p.get('question_type')}",
            f"- **协同决策中间数据（审核裁判 Agent）**：verdict={d.get('verdict')} ｜ 知识溯源率={d.get('verification_rate')} ｜ 溯源核验={d.get('traceability_verified')}/{d.get('traceability_total')} ｜ 事实准确率={d.get('fact_accuracy')} ｜ 逻辑完整度={d.get('logic_completeness')} ｜ 教学适配度={d.get('pedagogical_fit')} ｜ 复核分={d.get('review_score')}",
            f"- **最终资源（领域生成 Agent）**：讲义结论摘录「{str(lec_txt)[:160]}…」；含练习指南、分阶测验、知识引用（详见 JSON）。",
            "",
        ]
        (OUT / f"{sid}_io.json").write_text(
            json.dumps(ex, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (OUT / "README.md").write_text("\n".join(readme), encoding="utf-8")
    print(f"导出 {len(chosen)} 组 I/O 示例到 {OUT}")
    for ex in chosen:
        print(" -", ex["session_id"],
              "|", ex["input_profile"].get("knowledge_level"),
              "|", ex["input_profile"].get("domain_hint"))


if __name__ == "__main__":
    main()
