"""三档模型连通性测试 - 真实API调用"""

import asyncio
import sys
import time
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.llm_client import LLMClient, ModelTier


async def test_tier(client: LLMClient, tier: ModelTier, tier_name: str):
    """测试单个模型档位"""
    print(f"\n{'='*60}")
    print(f"测试 [{tier_name}] tier={tier.value}")
    print(f"{'='*60}")

    start = time.time()
    try:
        # 简单问答测试
        response = await client.chat(
            messages=[
                {"role": "system", "content": "你是一个测试助手，请简短回答。"},
                {"role": "user", "content": "请回复：连通测试成功。然后告诉我1+1等于几。"},
            ],
            tier=tier,
            temperature=0.0,
            max_tokens=100,
        )
        elapsed = time.time() - start
        print(f"✅ 连通成功 | 耗时 {elapsed:.2f}s")
        print(f"响应: {response[:200]}")
        return True

    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ 连通失败 | 耗时 {elapsed:.2f}s")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        return False


async def test_json_mode(client: LLMClient, tier: ModelTier, tier_name: str):
    """测试 JSON 模式输出（编排器依赖此功能）"""
    print(f"\n{'='*60}")
    print(f"测试 JSON模式 [{tier_name}]")
    print(f"{'='*60}")

    start = time.time()
    try:
        response = await client.chat_json(
            messages=[
                {"role": "system", "content": "你是一个JSON生成器，必须返回合法JSON。"},
                {"role": "user", "content": '返回一个JSON: {"status": "ok", "value": 42}'},
            ],
            tier=tier,
            temperature=0.0,
            max_tokens=100,
        )
        elapsed = time.time() - start
        print(f"✅ JSON模式成功 | 耗时 {elapsed:.2f}s")
        print(f"原始响应: {response[:200]}")

        # 验证是否合法JSON
        import json
        try:
            parsed = json.loads(response)
            print(f"✅ JSON解析成功: {parsed}")
        except json.JSONDecodeError as je:
            print(f"⚠️ JSON解析失败: {je}")
            print(f"（这会导致三层兜底机制启动，但不影响连通性）")
        return True

    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ JSON模式失败 | 耗时 {elapsed:.2f}s")
        print(f"错误: {type(e).__name__}: {e}")
        return False


async def main():
    print("=" * 60)
    print("三档模型连通性测试开始")
    print("=" * 60)

    # 加载配置确认
    from backend.config import get_settings
    settings = get_settings()
    print(f"\n配置确认:")
    print(f"  中档: {settings.deepseek_model} @ {settings.deepseek_base_url}")
    print(f"  高档: {settings.openai_model} @ {settings.openai_base_url}")
    print(f"  低档: {settings.openai_mini_model} @ {settings.openai_base_url}")
    print(f"  超时: {settings.llm_timeout}s")

    # 检查key是否非空
    if not settings.deepseek_api_key:
        print("❌ DEEPSEEK_API_KEY 为空，请检查 .env")
        return
    if not settings.openai_api_key:
        print("❌ OPENAI_API_KEY 为空，请检查 .env")
        return

    print("\nkey 已配置，开始测试...")

    client = LLMClient()
    results = {}

    # 1. 中档 - DeepSeek
    results["中档(DeepSeek)"] = await test_tier(client, ModelTier.MID, "中档 DeepSeek")
    if results["中档(DeepSeek)"]:
        await test_json_mode(client, ModelTier.MID, "中档 DeepSeek")

    # 2. 高档 - qwen-max
    results["高档(qwen-max)"] = await test_tier(client, ModelTier.HIGH, "高档 qwen-max")
    if results["高档(qwen-max)"]:
        await test_json_mode(client, ModelTier.HIGH, "高档 qwen-max")

    # 3. 低档 - qwen-turbo
    results["低档(qwen-turbo)"] = await test_tier(client, ModelTier.LOW, "低档 qwen-turbo")
    if results["低档(qwen-turbo)"]:
        await test_json_mode(client, ModelTier.LOW, "低档 qwen-turbo")

    # 汇总
    print(f"\n{'='*60}")
    print("连通性测试汇总")
    print(f"{'='*60}")
    for name, ok in results.items():
        status = "✅ 通过" if ok else "❌ 失败"
        print(f"  {name}: {status}")

    passed = sum(results.values())
    total = len(results)
    print(f"\n结果: {passed}/{total} 档位连通成功")

    if passed == total:
        print("\n🎉 三档模型全部连通，可以进入端到端联调！")
    else:
        print(f"\n⚠️ {total - passed} 个档位失败，需先排查API配置")


if __name__ == "__main__":
    asyncio.run(main())
