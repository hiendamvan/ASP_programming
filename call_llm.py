from llm import llm_chat, PROVIDERS

messages = [
    {
        "role": "system",
        "content": "You are a helpful assistant."
    },
    {
        "role": "user",
        "content": "Xin chao"
    }
]

result = llm_chat(messages)

print(result["provider"])
print(result["content"])