"""真实LLM端到端联调 - 用真实API跑完整编排器主链路

测试场景：一个AI学习相关的真实问题，走完整主FSM
  IDLE → PROFILING → DISPATCHING → GENERATING → REVIEWING
  → FOCUSING → JUDGING → FORMATTING → COMPLETE

注意：知识库为Stub（返回空），但不影响主链路验证
"""

import asyncio
import sys
import time
import traceback
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from loguru import logger

# 降低日志级别，只显示关键信息
logger.remove()
logger.add(sys.stderr, level="INFO", format="<level>{level: <8}</level> | {message}")

from backend.core.orchestrator import Orchestrator
from backend.db.init_db import init_database
from backend.config import get_settings


async def run_real_e2e():
    """真实LLM端到端联调"""

    print("=" * 70)
    print("真实LLM端到端联调开始")
    print("=" * 70)

    # 1. 初始化数据库
    print("\n[1/4] 初始化数据库...")
    init_database()
    print("  ✅ 数据库就绪")

    # 2. 确认LLM配置
    settings = get_settings()
    print(f"\n[2/4] LLM配置确认:")
    print(f"  中档: {settings.deepseek_model}")
    print(f"  高档: {settings.openai_model}")
    print(f"  低档: {settings.openai_mini_model}")
    print(f"  超时: {settings.llm_timeout}s")

    # 3. 创建编排器
    print(f"\n[3/4] 创建编排器...")
    orchestrator = Orchestrator()
    print("  ✅ 编排器就绪")

    # 4. 跑真实问题
    # 测试1: 澄清意图（验证澄清路径正常）
    print("\n" + "=" * 70)
    print("测试1: 澄清意图路径")
    print("=" * 70)
    question_clarify = "什么是RAG？"
    session_clarify = f"e2e_clarify_{int(time.time())}"
    print(f"  问题: {question_clarify}")

    start = time.time()
    result_clarify = await orchestrator.process_question(
        question=question_clarify,
        session_id=session_clarify,
        history=[],
    )
    elapsed = time.time() - start
    print(f"  耗时: {elapsed:.1f}s")

    if "error" in result_clarify:
        print(f"  ❌ 失败: {result_clarify['error']}")
    else:
        dispatch = result_clarify.get("dispatch_info")
        if dispatch:
            print(f"  意图: {dispatch.get('intent')}")
            options = result_clarify.get("clarification_options")
            if options:
                print(f"  ✅ 澄清选项返回: {len(options)} 个")
                for opt in options[:3]:
                    print(f"    - {opt}")
            else:
                print(f"  ⚠️ 澄清选项为空")

    # 测试2: 生成意图（跑完整主链路）
    print("\n" + "=" * 70)
    print("测试2: 生成意图完整主链路")
    print("=" * 70)

    question = "帮我详细讲解RAG检索增强生成的完整原理，包括向量检索和重排序的步骤，并给出一个Python代码示例"
    session_id = f"e2e_gen_{int(time.time())}"  # 唯一session避免画像缓存

    print(f"  问题: {question}")
    print(f"  Session: {session_id}")
    print(f"\n  ⏳ 正在调用真实LLM跑完整主链路...")
    print(f"  （预计耗时1-3分钟，涉及约10次LLM调用）\n")

    start = time.time()
    try:
        result = await orchestrator.process_question(
            question=question,
            session_id=session_id,
            history=[],  # 首次提问
        )
        elapsed = time.time() - start

        print(f"\n{'='*70}")
        print(f"主链路完成！总耗时: {elapsed:.1f}s")
        print(f"{'='*70}")

        # 检查结果
        if "error" in result:
            print(f"\n❌ 主链路失败: {result['error']}")
            print(f"  状态: {result.get('state')}")
            return False

        # 打印各阶段结果
        print("\n--- 阶段1: 学情画像 ---")
        profile = result.get("profile")
        if profile:
            print(f"  ✅ 画像生成成功")
            print(f"  知识水平: {profile.get('knowledge_level')}")
            print(f"  背景: {profile.get('background')}")
            print(f"  意图: {profile.get('intent_type')}")
            print(f"  领域: {profile.get('domain_hint')}")
            print(f"  复杂度: {profile.get('complexity_estimate')}")
        else:
            print(f"  ❌ 画像为空")

        print("\n--- 阶段2: 调度信息 ---")
        dispatch = result.get("dispatch_info")
        if dispatch:
            print(f"  ✅ 调度成功")
            print(f"  意图: {dispatch.get('intent')}")
            segments = dispatch.get("segments", [])
            print(f"  段数: {len(segments)}")
            for seg in segments:
                print(f"    段{seg['seg_id']}: domain={seg['domain']}, 候选数={len(seg['candidates'])}")
                for c in seg["candidates"]:
                    print(f"      - {c['agent_id']} (score={c['composite_score']:.3f})")
        else:
            print(f"  ❌ 调度为空")

        print("\n--- 阶段3: 裁判裁决 ---")
        verdict = result.get("judge_verdict")
        if verdict:
            print(f"  ✅ 裁判完成")
            print(f"  最终裁决: {verdict.get('verdict')}")
            print(f"  验证率: {verdict.get('overall_verification_rate')}")
            judges = verdict.get("judges", [])
            print(f"  裁判数: {len(judges)}")
            for j in judges:
                print(f"    - {j.get('role')}: {j.get('judgment')} (confidence={j.get('confidence')})")
        else:
            print(f"  ❌ 裁判为空")

        print("\n--- 阶段4: 资源包（最终交付） ---")
        pkg = result.get("resource_package")
        if pkg:
            print(f"  ✅ 资源包生成成功")
            lecture = pkg.get("lecture")
            if lecture:
                print(f"  讲义标题: {lecture.get('title', 'N/A')}")
                content = lecture.get('content_markdown', '')
                print(f"  讲义长度: {len(content)} 字符")
                print(f"  讲义摘要: {content[:300]}...")
                refs = lecture.get('knowledge_refs_display', [])
                print(f"  溯源标注: {len(refs)} 条")

            practice = pkg.get("practice_guide")
            if practice:
                steps = practice.get('steps_markdown', '')
                print(f"  实操指南: {len(steps)} 字符")
                print(f"  实操目标: {practice.get('goal', 'N/A')}")

            quiz = pkg.get("quiz")
            if quiz:
                questions = quiz.get("questions", [])
                print(f"  测试题: {len(questions)} 题")
                for i, q in enumerate(questions):
                    print(f"    Q{i+1}: [{q.get('type', '?')}] {q.get('question', 'N/A')[:60]}")
        else:
            print(f"  ❌ 资源包为空")

        # 总结
        print(f"\n{'='*70}")
        print("联调总结")
        print(f"{'='*70}")
        checks = {
            "画像生成": profile is not None,
            "调度成功": dispatch is not None,
            "裁判裁决": verdict is not None,
            "资源包": pkg is not None,
        }
        for name, ok in checks.items():
            print(f"  {'✅' if ok else '❌'} {name}")

        all_ok = all(checks.values())
        if all_ok:
            print(f"\n🎉 真实LLM端到端联调成功！主链路全程畅通。")
        else:
            failed = [n for n, ok in checks.items() if not ok]
            print(f"\n⚠️ 部分阶段异常: {', '.join(failed)}")

        return all_ok

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n{'='*70}")
        print(f"❌ 主链路崩溃！耗时: {elapsed:.1f}s")
        print(f"{'='*70}")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        print(f"\n完整堆栈:")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(run_real_e2e())
    sys.exit(0 if success else 1)
