import os

import openai

from utils import MODEL, SYSTEM_PROMPT

client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1", api_key=os.environ.get("GROQ_API_KEY")
)


class AI:
    def __init__(self):
        pass

    def chat(self, command: str) -> str:
        chat_completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": command,
                },
            ],
        )
        return chat_completion.choices[0].message.content or ""


if __name__ == "__main__":
    ai = AI()
    while True:
        q = input("$ ")
        if q != "":
            response = ai.chat(q)
            if response != "":
                print(response)
