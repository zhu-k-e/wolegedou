"""干净重跑零失误核查关卡。
对 benchmark_clean_rerun.log 与数据库做硬性检查，任一失误即 FAIL，要求重跑。
检查项：
  1. 日志 Arrearage(欠费) 次数 == 0
  2. 聚焦输出重试耗尽(降级兜底) 次数 == 0
  3. LLM调用失败[tier=high] 次数 == 0
  4. qwen-max 输出被截断 次数 == 0（生成完整性）
  5. 主FSM完成 == 100
  6. 资源包生成完成(零降级) == 100
  7. 末尾汇总 ok=100 error=0 partial=0
  8. DB: task_resources(bm_)==100 且 lecture 真实内容(>50字)==100
  9. DB: task_metrics(bm_) distinct session == 100
"""
import sqlite3
from pathlib import Path

LOG = Path("data/benchmark_clean_rerun.log")
DB = Path("data/wolegedou.db")


def main():
    log = LOG.read_text(encoding="utf-8", errors="ignore")
    lines = log.splitlines()
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, cond, detail))

    arrear = sum("Arrearage" in l for l in lines)
    chk("qwen-max 欠费(Arrearage)=0", arrear == 0, f"出现 {arrear} 次")
    exhausted = sum("聚焦输出重试耗尽" in l for l in lines)
    chk("聚焦输出降级兜底=0", exhausted == 0, f"出现 {exhausted} 次")
    high_fail = sum("LLM调用失败[tier=high" in l for l in lines)
    chk("HIGH档调用失败=0", high_fail == 0, f"出现 {high_fail} 次")
    trunc = sum("仍被截断" in l for l in lines)  # 仅统计重试耗尽、返回残缺内容的放弃标记
    chk("qwen-max 输出残缺(重试耗尽)=0", trunc == 0, f"出现 {trunc} 次")
    fsm = sum("主FSM完成" in l for l in lines)
    chk("主FSM完成=100", fsm == 100, f"实际 {fsm}")
    zero_deg = sum("资源包生成完成(零降级)" in l for l in lines)
    chk("资源包零降级=100", zero_deg == 100, f"实际 {zero_deg}")
    summary_ok = "ok=100" in log and "error=0" in log and "partial=0" in log
    chk("末尾汇总 ok=100/error=0/partial=0", summary_ok, "")

    # DB 检查
    c = sqlite3.connect(str(DB))
    res_n = c.execute("select count(*) from task_resources where session_id like 'bm_%'").fetchone()[0]
    lec_ok = c.execute(
        "select count(*) from task_resources where session_id like 'bm_%' "
        "and lecture is not null and length(lecture)>50").fetchone()[0]
    tm_n = c.execute(
        "select count(distinct session_id) from task_metrics where session_id like 'bm_%'").fetchone()[0]
    c.close()
    chk("task_resources(bm_)=100", res_n == 100, f"实际 {res_n}")
    chk("lecture真实内容>50字=100", lec_ok == 100, f"实际 {lec_ok}")
    chk("task_metrics distinct session=100", tm_n == 100, f"实际 {tm_n}")

    print("=" * 56)
    all_ok = True
    for name, cond, detail in checks:
        mark = "✅ PASS" if cond else "❌ FAIL"
        if not cond:
            all_ok = False
        print(f"  {mark}  {name}" + (f"  ({detail})" if detail else ""))
    print("=" * 56)
    verdict = "CLEAN_RUN_OK" if all_ok else "CONTAMINATED_REQUIRE_RERUN"
    print(f"VERDICT={verdict}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
