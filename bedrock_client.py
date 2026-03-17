from invoice_config import *
from invoice_processor import *
import os
import io
import re
import json
import base64
import tempfile
import traceback
from typing import List, Dict, Any, Optional
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)
PROMPT_FILE = os.path.join(BASE_DIR, "invoice_prompt.txt")


def load_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()


prompt_text = load_prompt()

def call_bedrock_model(prompt: str, image_path: Optional[str] = None, max_tokens: int = 4096) -> str:
    """
    Build messages content (text + optional image) and call bedrock-runtime invoke_model.
    Returns textual output (concatenated 'text' parts) or empty string on error.
    """
    content = [{"type": "text", "text": prompt}]
    if image_path:
        with open(image_path, "rb") as f:
            img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode()
        # determine media type
        ext = os.path.splitext(image_path)[1].lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        media_type = f"image/{ext}"
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": img_b64
            }
        })

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": content
            }
        ]
    }

    try:
        response = BRT.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body)
        )
        raw = response["body"].read().decode("utf-8")
        parsed = json.loads(raw)
        out_text = ""
        for p in parsed.get("content", []):
            if p.get("type") == "text":
                out_text += p.get("text", "")
        return out_text
    except Exception as e:
        traceback.print_exc()
        return ""
    
# ------------------- InvoiceProcessor -------------------
class InvoiceProcessor:
    def __init__(self, debug: bool = True):
        self.debug = debug
        self.temp_files: List[str] = []

    def log(self, *args):
        if self.debug:
            print("[DEBUG]", *args)

    def cleanup(self):
        for f in list(self.temp_files):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
            try:
                self.temp_files.remove(f)
            except Exception:
                pass

    def encode_image_b64(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    def load_invoice_prompt(self):
        with open("invoice_prompt.txt", "r", encoding="utf-8") as f:
            return f.read()

    def extract_with_bedrock(self, image_path: str, ocr_text: str, page_number: int, total_pages: int, all_ocr_text: str = "") -> Dict[str, Any]:
        """
        Prepare prompt, call Bedrock (Claude Sonnet 4), and return parsed JSON dict.
        Mirrors the menu script method (text + image in messages).
        """
        try:
            # construct context-aware prompt (JSON-only)
            page_context = ""
            if page_number == 1:
                page_context = "This is the FIRST page - prioritize header invoice #, dates, customer/vendor details."
            elif page_number == total_pages:
                page_context = "This is the LAST page - prioritize totals (subtotal, tax, total) and final line items."
            else:
                page_context = f"This is page {page_number} of {total_pages} - focus on line items."

            base_prompt = load_prompt()

            prompt = base_prompt.replace("{page_context}", page_context)\
                   .replace("{ocr_text}", ocr_text[:2000])\
                   .replace("{all_ocr_text}", all_ocr_text[:2000])

            # Use call_bedrock_model which sends text + image
            model_text = call_bedrock_model(prompt, image_path=image_path, max_tokens=4096)
            if not model_text:
                return self.fallback_extraction(ocr_text, page_number, all_ocr_text)

            # Clean model response and extract JSON
            model_text = re.sub(r"```json\s*", "", model_text, flags=re.IGNORECASE)
            model_text = re.sub(r"```\s*", "", model_text, flags=re.IGNORECASE)
            parsed = extract_json_from_model_text(model_text)
            if not parsed:
                return self.fallback_extraction(ocr_text, page_number, all_ocr_text)

            parsed["page_number"] = page_number
            return self.clean_extracted_data(parsed, ocr_text)

        except Exception as e:
            traceback.print_exc()
            return self.fallback_extraction(ocr_text, page_number, all_ocr_text)

    def fallback_extraction(self, ocr_text: str, page_number: int, all_ocr_text: str = "") -> Dict[str, Any]:
        """
        Simple regex-based fallback extraction (Invoice No, Date).
        """
        def find_first(patterns, text):
            for p in patterns:
                m = re.search(p, text, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            return None

        search_text = all_ocr_text or ocr_text

        invoice_patterns = [
            r'Invoice\s*No[:\s]*([A-Z0-9\-\/]+)',
            r'Invoice\s*Number[:\s]*([A-Z0-9\-\/]+)',
            r'Inv[:\s]*([A-Z0-9\-\/]+)'
        ]
        date_patterns = [
            r'Invoice\s*Date[:\s]*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})',
            r'Date[:\s]*([0-9]{1,2}[-/][A-Za-z]{3,9}[-/][0-9]{2,4})'
        ]

        return {
            "page_number": page_number,
            "invoiceNo": find_first(invoice_patterns, search_text),
            "invoiceDate": find_first(date_patterns, search_text),
            "dueDate": None,
            "purchaseOrder": None,
            "customerCompany": None,
            "customerContact": None,
            "customerAddr1": None,
            "customerAddr2": None,
            "customerCity": None,
            "customerState": None,
            "customerZIP": None,
            "terms": None,
            "vendorName": None,
            "vendorAddress": None,
            "subtotal": None,
            "tax": None,
            "total": None,
            "line_items": [],
            "extraction_method": "fallback"
        }

    def clean_extracted_data(self, data: Dict[str, Any], ocr_text: str) -> Dict[str, Any]:
        """
        Normalize fields: remove currency symbols, enforce strings for items, return safe defaults.
        """
        # Normalize invoice number
        if data.get("invoiceNo"):
            data["invoiceNo"] = re.sub(r"[^\w\-\./]", "", str(data["invoiceNo"]).strip())

        # Clean numeric-like fields (strip currency signs and commas)
        for field in ("subtotal", "tax", "total"):
            v = data.get(field)
            if v is None:
                data[field] = "0"
            else:
                s = str(v).strip()
                s = re.sub(r'[^\d.\-]', '', s)
                data[field] = s if s else "0"

        # Clean line items
        cleaned = []
        for item in data.get("line_items", []):
            qty = str(item.get("qty", "") or "").strip()
            name = str(item.get("ItemName", "") or "").strip()
            desc = str(item.get("itemDescription", "") or "").strip()
            rate = str(item.get("rate", "") or "").strip()
            rate = re.sub(r'[^\d.\-]', '', rate) if rate else "0"
            amt = str(item.get("amt", "") or "").strip()
            amt = re.sub(r'[^\d.\-]', '', amt) if amt else "0"
            prod = str(item.get("productCode", "") or "").strip()

            # require either name or description to include item
            if name or desc:
                cleaned.append({
                    "qty": qty if qty else "0",
                    "ItemName": name,
                    "itemDescription": desc,
                    "rate": rate if rate else "0",
                    "amt": amt if amt else "0",
                    "productCode": prod if prod else "0"
                })
        data["line_items"] = cleaned
        return data

    def consolidate_pages(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Consolidate multiple page outputs into a single invoice.
        Prefers header info from first page and totals from last page.
        Aggregates line items across pages and calculates totals if needed.
        """
        if not pages:
            return {}

        consolidated = {
            "invoiceNo": None,
            "invoiceDate": None,
            "dueDate": None,
            "purchaseOrder": None,
            "customerCompany": None,
            "customerContact": None,
            "customerAddr1": None,
            "customerAddr2": None,
            "customerCity": None,
            "customerState": None,
            "customerZIP": None,
            "terms": None,
            "vendorName": None,
            "vendorAddress": None,
            "subtotal": None,
            "tax": None,
            "total": None,
            "items": []
        }

        first = pages[0]
        last = pages[-1]

        # Header fields from first page
        headers = ["invoiceNo", "invoiceDate", "purchaseOrder", "customerCompany", "customerContact", "customerAddr1", "customerAddr2", "vendorName", "vendorAddress"]
        for h in headers:
            if first.get(h):
                consolidated[h] = first[h]

        # Totals from last page
        totals = ["subtotal", "tax", "total", "dueDate", "terms"]
        for t in totals:
            if last.get(t):
                consolidated[t] = last[t]

        # Fill missing from other pages
        for page in pages:
            for k in consolidated.keys():
                if k == "items":
                    continue
                if not consolidated[k] and page.get(k):
                    consolidated[k] = page[k]

        # Aggregate line items
        all_items = []
        for page in pages:
            for it in page.get("line_items", []):
                if it.get("ItemName") or it.get("itemDescription"):
                    all_items.append({
                        "qty": it.get("qty", "0"),
                        "ItemName": it.get("ItemName", ""),
                        "itemDescription": it.get("itemDescription", ""),
                        "rate": it.get("rate", "0"),
                        "amt": it.get("amt", "0"),
                        "productCode": it.get("productCode", "0")
                    })
        consolidated["items"] = all_items

        # If total missing, try to compute from amounts
        if (not consolidated.get("total") or str(consolidated.get("total")).strip() in ("", "0")) and all_items:
            try:
                s = 0.0
                for it in all_items:
                    amt_str = str(it.get("amt", "0"))
                    amt_clean = re.sub(r'[^\d.\-]', '', amt_str)
                    if amt_clean:
                        s += float(amt_clean)
                consolidated["total"] = f"{s:.2f}"
            except Exception:
                pass

        # Defaults for subtotal/tax if None
        for f in ("subtotal", "tax", "total"):
            if consolidated.get(f) is None:
                consolidated[f] = "0"

        return consolidated

    def process_invoice(self, file_path: str) -> (List[Dict[str, Any]], Dict[str, Any]): # type: ignore
        """
        Full pipeline:
        - convert pdf -> images (PyMuPDF) OR single image accepted
        - OCR per page
        - call Bedrock per page with text+image
        - consolidate pages into final invoice dict
        """
        pages_data = []
        all_ocr = ""

        # If PDF
        if file_path.lower().endswith(".pdf"):
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
            image_paths = pdf_to_images(pdf_bytes, zoom=RENDER_DPI / 72.0)  # zoom approx DPI conversion
            self.temp_files.extend(image_paths)
        else:
            # single image
            image_paths = [file_path]

        total_pages = len(image_paths)
        # First pass: OCR to build context
        ocr_texts = []
        for i, ip in enumerate(image_paths, start=1):
            proc = preprocess_image_for_ocr(ip)
            self.temp_files.append(proc)
            text = ocr_image_to_text(proc)
            ocr_texts.append(text)
            all_ocr += f"\n--- Page {i} ---\n{text}"

        # Second pass: call model per page (with full context)
        for i, (ip, ocr_t) in enumerate(zip(image_paths, ocr_texts), start=1):
            page_json = self.extract_with_bedrock(ip, ocr_t, i, total_pages, all_ocr)
            pages_data.append(page_json)

        consolidated = self.consolidate_pages(pages_data)
        return pages_data, consolidated