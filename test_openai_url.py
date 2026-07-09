from openai import OpenAI
import httpx

client = OpenAI(api_key="123", base_url="https://robin-claude.openai.azure.com/openai/deployments/Kimi-K2.6")
print(client.chat.completions._client._base_url.join("chat/completions"))
