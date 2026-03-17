from invoice_config import *
import os
import io
import re
import json
import base64
import tempfile
import traceback
from typing import List, Dict, Any, Optional
from datetime import datetime
import fitz
import cv2
import pytesseract
from PIL import Image
import uuid
def save_temp_image_from_pil(img: Image.Image) -> str:
    fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="page_")
    os.close(fd)
    img.save(tmp_path, format="PNG")
    return tmp_path

def pdf_to_images(pdf_bytes: bytes, zoom: float = 2.0) -> List[str]:
    """
    Convert PDF bytes to list of temporary PNG file paths using PyMuPDF.
    Returns list of file paths.
    """
    images = []
    doc = fitz.open("pdf", pdf_bytes)
    mat = fitz.Matrix(zoom, zoom)
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        tmp_path = save_temp_image_from_pil(image)
        images.append(tmp_path)
    doc.close()
    return images

def preprocess_image_for_ocr(image_path: str) -> str:
    """
    Basic preprocessing: read, optionally resize, convert to grayscale & adaptive threshold.
    Returns path to processed temporary image (PNG).
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return image_path

        h, w = img.shape[:2]
        if max(h, w) < MIN_IMAGE_SIZE:
            scale = TARGET_SIZE / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
        sharpened = cv2.filter2D(gray, -1, kernel)

        processed = cv2.adaptiveThreshold(
            sharpened, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            25, 6
        )

        fd, tmp_path = tempfile.mkstemp(prefix="proc_", suffix=".png")
        os.close(fd)
        cv2.imwrite(tmp_path, processed)
        return tmp_path
    except Exception:
        return image_path

def ocr_image_to_text(image_path: str) -> str:
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        return text or ""
    except Exception:
        return ""

def extract_json_from_model_text(text: str) -> Dict[str, Any]:
    """
    Find the first JSON object in `text` and parse it. If parsing fails, return {}.
    """
    if not text:
        return {}
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE)
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    candidate = m.group(0) if m else t
    # remove trailing commas before closing braces/brackets
    candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except Exception:
        # try locating outermost braces
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(candidate[start:end+1])
            except Exception:
                return {}
    return {}

import uuid
from datetime import datetime

def parse_date_safe(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except:
            try:
                return datetime.strptime(value, "%d/%m/%Y")
            except:
                return None


def map_ocr_to_inward(ocr):
    now = datetime.now().isoformat()

    inward = {
        "nvarInwardID": ocr.get("purchaseOrder", ""),
        "dtInwardDate": ocr.get("invoiceDate", ""),
        "nvarReferenceNo": ocr.get("invoiceNo", ""),
        "nvarInwardBy": ocr.get("vendorName", ""),
        "nvarDescription": f"Due Date: {ocr.get('dueDate')}" if ocr.get("dueDate") else "",
        "dcmlInwardTotalCost": ocr.get("total", 0),
        "dtCreatedDate": now,
        "dtModifiedDate": now,
        "bitIsDeleted": False,
        "IsEdit": False,
        "VendorState": ocr.get("customerState", ""),
        "lstInwardItems": []
    }

    vendors = {
        "nvarCompany": ocr.get("customerCompany", ""),
        "nvarFirst_Name": ocr.get("customerContact", ""),
        "nvarAddress_1": ocr.get("customerAddr1", ""),
        "nvarAddress_2": ocr.get("customerAddr2", ""),
        "nvarCity": ocr.get("customerCity", ""),
        "nvarState": ocr.get("customerState", ""),
        "nvarZip_Code": ocr.get("customerZIP", ""),
        "nvarVendor_Terms": ocr.get("terms", ""),
    }

    inward_items = []
    items = ocr.get("items", [])

    for index, item in enumerate(items):
        inward_items.append({
            "unqRowID": str(uuid.uuid4()),
            "nvarInwardID": ocr.get("purchaseOrder", ""),
            "nvarItemNum": item.get("productCode", ""),
            "nvarItemName": item.get("ItemName", ""),
            "nvarCaseOrIndividual": item.get("itemDescription", ""),
            "dcmlInwardQty": item.get("qty", 0),
            "dcmlItemCost": item.get("rate", 0),
            "dcmlInwardCost": item.get("amt", 0),
            "intStatus": 1,
            "nvarOrderItemCounter": str(index + 1),
            "intNumPerCase": None,
            "intStockUnit": 1,
            "dtCreatedDate": now,
            "dtModifiedDate": now,
            "bitIsDeleted": False,
            "Index": index
        })

    inward["lstInwardItems"] = inward_items

    return {
        "ORTP_Inward": inward,
        "ORTP_Vendors": vendors,
        "ORTP_InwardItems": inward_items
    }

# -------------- Replace None → "0" Utility ------------------
def replace_none_with_zero(obj):
    if isinstance(obj, dict):
        return {k: replace_none_with_zero(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_none_with_zero(i) for i in obj]
    elif obj is None:
        return "0"
    return obj

