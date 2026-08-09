import time
from typing import List, Dict

from openai import OpenAI
from google import genai
import cohere
import os
from dotenv import load_dotenv
load_dotenv()


# ==========================
# API Keys
# ==========================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY =  os.getenv("OPENROUTER_API_KEY")
#GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# COHERE_API_KEY = os.getenv("COHERE_API_KEY")


# ==========================
# Clients
# ==========================

print(repr(GROQ_API_KEY))
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# cohere_client = cohere.ClientV2(api_key=COHERE_API_KEY)


# ==========================
# Individual Call Functions
# ==========================
def call_groq(messages, temperature=0):
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content


def call_openrouter(messages, temperature=0):
    response = openrouter_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content


# def call_gemini(messages, temperature=0):
#     prompt = "\n".join(
#         f"{m['role']}: {m['content']}"
#         for m in messages
#     )

#     response = gemini_client.models.generate_content(
#         model="gemini-3.5-flash-lite",
#         contents=prompt,
#         config={
#             "temperature": temperature,
#         }
#     )

#     return response.text


# def call_cohere(messages, temperature=0):
#     response = cohere_client.chat(
#         model="command-a-plus",
#         messages=messages,
#         temperature=temperature,
#     )

#     return response.message.content[0].text

PROVIDERS = [
    ("groq", call_groq),
    ("openrouter", call_openrouter),
    # ("gemini", call_gemini),
    # ("cohere", call_cohere),
]


def llm_chat(
    messages: List[Dict],
    temperature: float = 0,
    providers=PROVIDERS,
):
    last_error = None

    for name, func in providers:
        try:
            print(f"Trying {name}...")

            answer = func(
                messages=messages,
                temperature=temperature,
            )

            print(f"Success: {name}")

            return {
                "provider": name,
                "content": answer,
            }

        except Exception as e:
            last_error = e
            print(f"{name} failed: {e}")

            time.sleep(1)

    raise RuntimeError(
        f"All providers failed.\nLast error: {last_error}"
    )

