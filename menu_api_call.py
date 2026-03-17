# debug_code.py

import base64
import json
import os
import re
import uuid
from openai import OpenAI
from env_loader import load_env_file

load_env_file()

MODEL_ID = os.getenv("OPENAI_MODEL", "gpt-4.1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY. Set it in your environment or .env file.")

client = OpenAI(api_key=OPENAI_API_KEY)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

PROMPT_FILE = os.path.join(BASE_DIR, "2_v_prompt_menu.txt")


def load_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()


prompt_text = load_prompt()


def extract_menu_from_image(image_bytes):

    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.responses.create(
        model=MODEL_ID,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt_text},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{encoded_image}",
                    },
                ],
            }
        ],
        max_output_tokens=5000,
        temperature=0,
    )

    raw_text = response.output[0].content[0].text.strip()

    raw_text = re.sub(r"^```json\s*", "", raw_text)
    raw_text = re.sub(r"^```", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    parsed_json = json.loads(raw_text)

    # 🔹 Generate ONE UUID
    unique_id = str(uuid.uuid4())

    chatgpt_filename = f"chatgpt_{unique_id}.json"
    chatgpt_path = os.path.join(OUTPUT_DIR, chatgpt_filename)

    with open(chatgpt_path, "w", encoding="utf-8") as f:
        json.dump(parsed_json, f, indent=2, ensure_ascii=False)

    return parsed_json, unique_id, chatgpt_path