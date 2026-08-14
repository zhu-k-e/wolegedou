"""跑前真生成探测：用 LLMClient(HIGH/qwen-max) 真实生成内容，确认余额健康。
不是 ping，是让 qwen-max 实际产出一段教育文字，验证：(1) 不抛欠费异常；
(2) 返回真实非空内容。探测通过才允许启动 benchmark 干净重跑。
"""
import asyncio
import sys
from backend.services.llm_client import LLMClient, ModelTier


PROMPTS = [
    "请用一句话解释什么是大模型微调中的 LoRA。",
    "简要说明 RAG 系统中向量检索的基本流程。",
    "用一句话解释 Transformer 的自注意力机制。",
]


async def main():
    client = LLMClient()
    ok = 0
    for i, p in enumerate(PROMPTS, 1):
        try:
            text = await client.chat(
                messages=[{"role": "user", "content": p}],
                tier=ModelTier.HIGH,
                temperature=0.3,
                max_tokens=256,
                max_retries=1,
            )
            if text and len(text.strip()) >= 20:
                print(f"[探测 {i}/3] OK  len={len(text.strip())}  preview={text.strip()[:40]!r}")
                ok += 1
            else:
                print(f"[探测 {i}/3] FAIL 返回内容过短或为空: {text!r}")
        except Exception as e:
            print(f"[探测 {i}/3] FAIL 异常: {type(e).__name__}: {e}")
            print("PREFLIGHT_RESULT=FAIL")
            return
    if ok == len(PROMPTS):
        print("PREFLIGHT_RESULT=PASS")
    else:
        print("PREFLIGHT_RESULT=FAIL")


if __name__ == "__main__":
    asyncio.run(main())
