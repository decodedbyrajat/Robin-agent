import asyncio
from agent.auxiliary_client import async_call_llm

async def main():
    try:
        res = await async_call_llm(
            provider="custom",
            model="Kimi-K2.6",
            base_url="https://robin-claude.openai.azure.com/openai/deployments/Kimi-K2.6?api-version=2024-05-01-preview",
            messages=[{"role": "user", "content": "hello"}],
        )
        print("Success:", res)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
