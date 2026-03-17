# main.py

import os
import tempfile
import requests
from fastapi import FastAPI, HTTPException, Depends
from fastapi import File, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from menu_api_call import extract_menu_from_image
from create_menu_json import save_transformed_json
from invoice_config import *
from models import *
from invoice_processor import *
from bedrock_client import *
from pathlib import Path
from datetime import datetime
from fastapi.responses import FileResponse
import os
import json
import traceback
import urllib.parse
import httpx
import uvicorn
from fastapi.concurrency import run_in_threadpool
import httpx
import tempfile
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from invoice_processor import *
from utils import *

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

from pathlib import Path
@app.get("/", response_model=HealthResponse)
async def root():
    return {"status": "running", "timestamp": datetime.now().isoformat(), "version": "1.0.0"}

@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "version": "1.0.0"}

from fastapi import Request
# @app.post("/process-invoice", response_model=ProcessingResponse, dependencies=[Depends(verify_token)])
@app.post("/process-invoice", response_model=ProcessingResponse, dependencies=[Depends(verify_token)])
async def process_invoice_endpoint(
    request: Request,
    file: UploadFile = File(...),
    authorized: bool = Depends(verify_token) 
):
    print(request.headers)

    # --- Validate Token (explicit, not hidden dependency) ---
    # verify_token(token)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    allowed = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"]
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_name = f"{ts}_{file.filename}"
    upload_path = os.path.join(UPLOAD_DIR, upload_name)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    try:
        # --- Save uploaded file ---
        contents = await file.read()
        with open(upload_path, "wb") as fw:
            fw.write(contents)

        processor = InvoiceProcessor(debug=True)

        # --- Run processor in separate thread ---
        pages_data, consolidated = await run_in_threadpool(
            processor.process_invoice, upload_path
        )

        # --- Map inward entries ---
        try:
            inward_mapped = map_ocr_to_inward(consolidated)
        except Exception as e:
            inward_mapped = {}
            print("Mapping error:", e)

        # --- Save result JSON ---
        result_name = f"{ts}_{Path(file.filename).stem}_result.json"
        result_path = os.path.join(RESULTS_DIR, result_name)

        result_payload = {
            # "consolidated_invoice": consolidated,
            "inward_mapped": inward_mapped,
            # "page_details": pages_data,
            "processing_info": {
                "total_pages": len(pages_data),
                # "total_items": len(consolidated.get("items", [])),
                "processed_at": datetime.now().isoformat(),
                
            }
        }

        with open(result_path, "w", encoding="utf-8") as rf:
            json.dump(result_payload, rf, indent=2, ensure_ascii=False)

        # --- Convert consolidated to Pydantic model ---
        try:
            items = [LineItem(**it) for it in consolidated.get("items", [])]
            cons_copy = dict(consolidated)
            cons_copy["items"] = items
            model_data = ConsolidatedInvoice(**cons_copy)
            clean_data = replace_none_with_zero(model_data.dict())
        except Exception as e:
            print("Model conversion error:", e)
            clean_data = replace_none_with_zero(consolidated)

        return ProcessingResponse(
            success=True,
            message=f"Processed {len(pages_data)} page(s)",
            # data=clean_data,
            details={
                "pages_processed": len(pages_data),
                # "items_extracted": len(consolidated.get("items", [])),
                "result_file": result_name,
                "inward_data": inward_mapped
            }
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        try:
            if os.path.exists(upload_path):
                os.remove(upload_path)
        except:
            pass
        try:
            processor.cleanup()
        except:
            pass



@app.post("/process-invoice-url", response_model=ProcessingResponse, dependencies=[Depends(verify_token)])
async def process_invoice_url(
    payload: Dict[str, str],
    authorized: bool = Depends(verify_token)
):
    """
    Accepts JSON body {"fileurl": "..."}.
    Downloads the file to uploads/ and runs the same processing pipeline.
    Returns the same ProcessingResponse shape as /process-invoice.
    """
    # --- Validate Token (explicit, same as /process-invoice) ---
    # verify_token(token)

    fileurl = payload.get("fileurl")
    if not fileurl:
        raise HTTPException(status_code=400, detail="JSON body must include 'fileurl'")

    # Basic validation for URL scheme
    parsed = urllib.parse.urlparse(fileurl)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="fileurl must be an http or https url")

    # derive filename or fallback
    filename = Path(urllib.parse.unquote(parsed.path)).name or f"downloaded_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_path = os.path.join(UPLOAD_DIR, f"{ts}_{filename}")

    # Allowed file types
    allowed = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"]

    # Download file (async)
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(fileurl)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Failed to download file: status_code={resp.status_code}")
            content = resp.content

            # If filename had no allowed extension, try to infer from headers
            if not any(filename.lower().endswith(a) for a in allowed):
                ctype = resp.headers.get("content-type", "")
                if "pdf" in ctype:
                    upload_path = upload_path + ".pdf"
                elif "jpeg" in ctype or "jpg" in ctype:
                    upload_path = upload_path + ".jpg"
                elif "png" in ctype:
                    upload_path = upload_path + ".png"
                # otherwise leave as-is (will be validated later)

            # Save file
            with open(upload_path, "wb") as fw:
                fw.write(content)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error downloading file: {e}")

    # Basic file type verification after download
    ext = Path(upload_path).suffix.lower()
    if ext not in allowed:
        # try to proceed but warn / reject
        raise HTTPException(status_code=400, detail=f"Unsupported or unknown file type: {ext}")

    processor = InvoiceProcessor(debug=True)
    try:
        # Process in threadpool (same as /process-invoice)
        try:
            pages_data, consolidated = await run_in_threadpool(processor.process_invoice, upload_path)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Processing error: {e}")

        # --- Map inward entries (same mapping as /process-invoice) ---
        try:
            inward_mapped = map_ocr_to_inward(consolidated)
        except Exception as e:
            inward_mapped = {}
            print("Mapping error:", e)

        # --- Save result JSON (match /process-invoice naming & payload) ---
        result_name = f"{ts}_{Path(filename).stem}_result.json"
        result_path = os.path.join(RESULTS_DIR, result_name)
        result_payload = {
            "inward_mapped": inward_mapped,
            "processing_info": {
                "total_pages": len(pages_data),
                "processed_at": datetime.now().isoformat(),
                "source_file": fileurl
            }
        }
        with open(result_path, "w", encoding="utf-8") as rf:
            json.dump(result_payload, rf, indent=2, ensure_ascii=False)

        # --- Convert consolidated to Pydantic model (allowing numeric/str) ---
        try:
            items = [LineItem(**it) for it in consolidated.get("items", [])]
            cons_copy = dict(consolidated)
            cons_copy["items"] = items
            model_data = ConsolidatedInvoice(**cons_copy)
            clean_data = replace_none_with_zero(model_data.dict())
        except Exception as e:
            print("Model conversion error:", e)
            clean_data = replace_none_with_zero(consolidated)

        # Return same response shape and fields as /process-invoice
        return ProcessingResponse(
            success=True,
            message=f"Processed {len(pages_data)} page(s)",
            # data=clean_data,
            details={
                "pages_processed": len(pages_data),
                "result_file": result_name,
                "inward_data": inward_mapped
            }
        )

    finally:
        # cleanup same as /process-invoice
        processor.cleanup()
        try:
            if os.path.exists(upload_path):
                os.remove(upload_path)
        except Exception:
            pass



@app.get("/results/{filename}", dependencies=[Depends(verify_token)])
async def get_result(filename: str):
    path = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Result not found")
    return FileResponse(path, media_type="application/json")