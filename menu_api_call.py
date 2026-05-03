# debug_code.py

import base64
import json
import os
import re
import uuid
from env_loader import load_env_file

load_env_file()

from invoice_config import BRT
from bedrock_usage_log import log_bedrock_call

MODEL_ID = os.getenv(
    "BEDROCK_MENU_MODEL_ID",
    "arn:aws:bedrock:us-east-1:078805859846:inference-profile/us.anthropic.claude-opus-4-7",
)

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

    content = [
        {"type": "text", "text": prompt_text},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": encoded_image,
            },
        },
    ]

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 5000,
        "messages": [{"role": "user", "content": content}],
    }

    response = BRT.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    raw = response["body"].read().decode("utf-8")
    parsed = json.loads(raw)
    raw_text = ""
    for part in parsed.get("content", []):
        if part.get("type") == "text":
            raw_text += part.get("text", "")
    raw_text = raw_text.strip()

    log_bedrock_call(
        source="menu_api_call",
        model_id=MODEL_ID,
        prompt=prompt_text,
        output=raw_text,
        parsed_response=parsed,
    )

    raw_text = re.sub(r"^```json\s*", "", raw_text)
    raw_text = re.sub(r"^```", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    parsed_json = json.loads(raw_text)

    # 🔹 Generate ONE UUID
    unique_id = str(uuid.uuid4())

    out_filename = f"bedrock_{unique_id}.json"
    out_path = os.path.join(OUTPUT_DIR, out_filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(parsed_json, f, indent=2, ensure_ascii=False)

    return parsed_json, unique_id, out_path
