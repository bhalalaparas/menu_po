# models.py

from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel

NumberOrStr = Union[str, float, int]

class LineItem(BaseModel):
    qty: Optional[str] = None
    ItemName: Optional[str] = None
    itemDescription: Optional[str] = None
    rate: Optional[NumberOrStr] = None
    amt: Optional[NumberOrStr] = None
    productCode: Optional[str] = None

class ConsolidatedInvoice(BaseModel):
    invoiceNo: Optional[str] = None
    invoiceDate: Optional[str] = None
    dueDate: Optional[str] = None
    purchaseOrder: Optional[str] = None
    customerCompany: Optional[str] = None
    customerContact: Optional[str] = None
    customerAddr1: Optional[str] = None
    customerAddr2: Optional[str] = None
    customerCity: Optional[str] = None
    customerState: Optional[str] = None
    customerZIP: Optional[str] = None
    terms: Optional[str] = None
    vendorName: Optional[str] = None
    vendorAddress: Optional[str] = None
    subtotal: Optional[NumberOrStr] = None
    tax: Optional[NumberOrStr] = None
    total: Optional[NumberOrStr] = None
    items: List[LineItem] = []

class ProcessingResponse(BaseModel):
    success: bool
    message: str
    data: Optional[ConsolidatedInvoice] = None
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class ProcessingMenuResponse(BaseModel):
    success: bool
    message: str
    output_file: Optional[str] = None
    data: Optional[Dict[str, List[Dict[str, Any]]]] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class ImageJSON(BaseModel):
    image_url: Optional[str] = None