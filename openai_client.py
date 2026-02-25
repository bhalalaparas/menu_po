import base64
from openai import OpenAI

client = OpenAI(api_key="sk-proj-GeDY--EfHGyYrr0rVHGT6v6SoNT3BlbkFJ23iNmqNTWPT3TzlyD72XYNEfkOnv62JdznFxoF-h_qDQYmBYBiwEQPT4JC70hW68zHB8iipxUA")
MODEL = "gpt-4.1"

def call_gpt_invoice_parser(prompt: str, image_path: str):

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}"
                        }
                    }
                ],
            }
        ],
        max_tokens=4096,
    )

    return response.choices[0].message.content