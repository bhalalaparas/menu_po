import re
import json
from preprocessing import pdf_to_images, preprocess_image, ocr_image
from openai_client import call_gpt_invoice_parser


class InvoiceProcessor:

    def process_invoice(self, file_path):

        if file_path.lower().endswith(".pdf"):
            image_paths = pdf_to_images(file_path)
        else:
            image_paths = [file_path]

        pages = []

        for img in image_paths:

            processed = preprocess_image(img)
            ocr_text = ocr_image(processed)

            prompt = f"""
Extract invoice data.
Return ONLY valid JSON.

Fields:
invoiceNo
invoiceDate
total
items (array)

OCR:
{ocr_text[:2000]}
"""

            response = call_gpt_invoice_parser(prompt, img)
            parsed = self.extract_json(response)
            pages.append(parsed)

        consolidated = self.consolidate_pages(pages)
        return pages, consolidated

    def extract_json(self, text):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                return {}
        return {}

    def consolidate_pages(self, pages):

        result = {
            "invoiceNo": None,
            "invoiceDate": None,
            "total": None,
            "items": []
        }

        for p in pages:
            if not result["invoiceNo"] and p.get("invoiceNo"):
                result["invoiceNo"] = p["invoiceNo"]

            if not result["invoiceDate"] and p.get("invoiceDate"):
                result["invoiceDate"] = p["invoiceDate"]

            if p.get("items"):
                result["items"].extend(p["items"])

            if p.get("total"):
                result["total"] = p["total"]

        return result