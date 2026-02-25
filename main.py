# main.py

import os
import tempfile
import requests
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from menu_api_call import extract_menu_from_image
from create_menu_json import save_transformed_json

import httpx
import tempfile
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from invoice_processor import InvoiceProcessor
from utils import verify_token

UPLOAD_DIR = "uploads"
RESULTS_DIR = "results"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

app = FastAPI()

STATIC_API_TOKEN = os.getenv(
    "STATIC_API_TOKEN",
    "qwertyuioplkjhgfdsazxcvbnm123"
)

security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != STATIC_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True


# ---------------- REQUEST MODEL ----------------
class FileURLRequest(BaseModel):
    fileurl: str

# ---------------- API ----------------
@app.post("/process-menu-url")
async def process_menu(
    payload: FileURLRequest,
    authorized: bool = Depends(verify_token)
):
    temp_file_path = None

    try:
        # 1️⃣ Download image
        response = requests.get(payload.fileurl, timeout=30)
        response.raise_for_status()

        # 2️⃣ Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name

        # 3️⃣ Read image bytes
        with open(temp_file_path, "rb") as f:
            image_bytes = f.read()

        # 4️⃣ Call ChatGPT
        chatgpt_json, unique_id, chatgpt_path = extract_menu_from_image(image_bytes)

        # 5️⃣ Transform JSON
        transformed_path = save_transformed_json(chatgpt_json, unique_id)

        return {
            "chatgpt_output_file": chatgpt_path,
            "transformed_output_file": transformed_path
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # 6️⃣ Delete temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

class InvoiceURLRequest(BaseModel):
    fileurl: str

@app.post("/process-invoice-url", dependencies=[Depends(verify_token)])
async def process_invoice_url(request: InvoiceURLRequest):

    # Download file
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(request.fileurl)

        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to download file")

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Save to temp file
    suffix = ".pdf"
    if "image" in response.headers.get("content-type", ""):
        suffix = ".png"

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_file.write(response.content)
    tmp_file.close()

    processor = InvoiceProcessor()

    pages, consolidated = await run_in_threadpool(
        processor.process_invoice, tmp_file.name
    )

    # Cleanup
    os.remove(tmp_file.name)

    return {
        "success": True,
        "pages_processed": len(pages),
        "data": consolidated
    }


@app.get("/health")
def health():
    return {"status": "healthy"}



