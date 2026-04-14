import requests
from config import MOONSHOT_API_KEY, MOONSHOT_URL

def chat(messages):
    try:
        r = requests.post(
            MOONSHOT_URL,
            headers={"Authorization": f"Bearer {MOONSHOT_API_KEY}"},
            json={
                "model":"moonshot-v1-8k",
                "messages":messages[-8:],
                "temperature":0.9,
                "max_tokens":120
            },
            timeout=10
        )
        return r.json()["choices"][0]["message"]["content"]
    except:
        return "..."
