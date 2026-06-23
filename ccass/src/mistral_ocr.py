"""
Mistral OCR Provider — drop-in replacement for EasyOCR in agent extraction pipelines.

Uses Mistral's document understanding API (mistral-ocr-latest) which handles:
- PDF text extraction with structure preservation
- Embedded images/logos (where EasyOCR fails)
- Chinese + English multilingual
- Tables

Usage:
    from mistral_ocr import ocr_pdf_page, ocr_image
    
    # OCR a single PDF page rendered as image
    text = ocr_pdf_page(pdf_bytes, page_num=0)
    
    # OCR an image file
    text = ocr_image('/tmp/page0.png')

Requires: MISTRAL_API_KEY in .env or environment
"""

import os, base64, json, logging
from io import BytesIO

logger = logging.getLogger(__name__)
def _load_key() -> str:
    """Read MISTRAL_API_KEY from environment or .env in project root."""
    key = os.environ.get("MISTRAL_API_KEY")
    if key and len(key) > 10:
        return key

    # Read from .env
    needle = "MISTRAL_API_KEY"
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(needle + "=") and not line.startswith("#"):
                    val = line.split("=", 1)[1]
                    if len(val) > 10:
                        return val
    raise RuntimeError("MISTRAL_API_KEY not found in env or .env files")


def _get_client():
    """Lazy-init Mistral client."""
    from mistralai.client import Mistral
    key = _load_key()
    return Mistral(api_key=key)


def ocr_image(image_path: str) -> str:
    """OCR a single image file. Returns extracted text."""
    from mistralai.client import models
    
    client = _get_client()
    
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    # Use mistral-ocr-latest via chat with the image
    messages = [
        models.UserMessage(
            role="user",
            content=[
                models.TextChunk(
                    type="text",
                    text="Extract ALL text from this image. Include Chinese characters exactly as they appear. Preserve the structure and order of text."
                ),
                models.ImageURLChunk(
                    type="image_url",
                    image_url=models.ImageURL(url=f"data:image/png;base64,{image_data}")
                )
            ]
        )
    ]
    
    try:
        response = client.chat.complete(
            model="mistral-ocr-latest",
            messages=messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Mistral OCR failed for {image_path}: {e}")
        return ""


def ocr_pdf_page(pdf_bytes: bytes, page_num: int = 0, zoom: float = 2.0) -> str:
    """Render a PDF page as image, then OCR it with Mistral.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        page_num: Page number to OCR (0-indexed)
        zoom: Render zoom factor (higher = better OCR, slower)
    
    Returns extracted text string.
    """
    import pymupdf
    
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if page_num >= doc.page_count:
        logger.warning(f"Page {page_num} out of range (max {doc.page_count-1})")
        doc.close()
        return ""
    
    page = doc[page_num]
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    
    # Save to temp PNG (unique per invocation to avoid concurrent overwrite)
    import tempfile as _tempfile
    with _tempfile.NamedTemporaryFile(suffix='.png', delete=False) as _tf:
        tmp_path = _tf.name
    pix.save(tmp_path)
    doc.close()
    
    text = ocr_image(tmp_path)
    
    # Cleanup
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    
    return text


def ocr_for_agent_extraction(pdf_bytes: bytes, known_agents: list[str] = None, 
                              stock_name: str = None, max_pages: int = 3) -> str | None:
    """Specialized OCR for HKEX placing agent extraction.
    
    Strategy:
    1. Extract text from pages 0-1 with PyMuPDF (fast)
    2. If no agent found in text, use Mistral native document OCR
    3. Match against known agent names list
    4. Apply quality filters
    
    Returns agent name string, or None if not found.
    """
    import pymupdf, re
    from mistralai.client import models
    
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    
    # Step 1: Fast text extraction first
    text = ""
    for pg in range(min(max_pages, doc.page_count)):
        text += doc[pg].get_text() + "\n"
    
    # Known agent matching on text
    agent = _match_agent_in_text(text, known_agents, stock_name)
    if agent:
        doc.close()
        return agent
    
    doc.close()
    
    # Step 2: Mistral native document OCR
    try:
        import tempfile
        client = _get_client()
        
        tmp_path = None
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name
        
        try:
            with open(tmp_path, 'rb') as f:
                file_content = f.read()
            
            uploaded = client.files.upload(
                file=models.File(
                    file_name="document.pdf",
                    content=file_content,
                    content_type="application/pdf",
                ),
                purpose="ocr"
            )
            
            signed_url = client.files.get_signed_url(file_id=uploaded.id)
            
            ocr_response = client.ocr.process(
                model="mistral-ocr-latest",
                document=models.DocumentURLChunk(
                    type="document_url",
                    document_url=signed_url.url,
                ),
                include_image_base64=False,
            )
            
            # Build text from OCR pages
            ocr_text = ""
            for page in ocr_response.pages[:max_pages]:
                ocr_text += page.markdown + "\n"
            
            agent = _match_agent_in_text(ocr_text, known_agents, stock_name)
            if agent:
                return agent
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            
    except Exception as e:
        logger.error(f"Mistral document OCR failed in agent extraction: {e}")
        # Fallback to page-by-page image OCR (chat-based)
        logger.info("Falling back to page-by-page image OCR for agent extraction")
        for pg in range(min(2, max_pages)):
            ocr_text = ocr_pdf_page(pdf_bytes, pg)
            if ocr_text:
                agent = _match_agent_in_text(ocr_text, known_agents, stock_name)
                if agent:
                    return agent
    
    return None


def _match_agent_in_text(text: str, known_agents: list[str] = None, 
                          stock_name: str = None) -> str | None:
    """Search text for known placing agent names. Returns agent name or None."""
    import re
    
    tl = text.lower()
    
    # Strategy 1: Known agent name match (preferred - zero garbage)
    if known_agents:
        # Sort by length descending to match longest first
        for agent in sorted(known_agents, key=len, reverse=True):
            if agent.lower() in tl:
                # Verify not company's own name
                if stock_name and len(stock_name) > 3 and stock_name.lower() in agent.lower():
                    continue
                # Quality check
                if _validate_agent(agent, stock_name):
                    return agent
    
    # Strategy 2: Pattern-based extraction (Placing Agent: NAME)
    patterns = [
        r'(?:Placing|PLACING)\s+Agent\s*[:\n]\s*([A-Z][A-Za-z\s&.,()\'\-]{6,80})',
        r'(?:Sole|SOLE)\s+Placing\s+Agent\s*[:\n]\s*([A-Z][A-Za-z\s&.,()\'\-]{6,80})',
        r'appointed\s+([A-Z][A-Za-z\s&.,()\'\-]{6,60})\s+(?:as|AS)\s+(?:the\s+)?(?:placing|Placing)\s+agent',
    ]
    
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            name = m.group(1).strip()
            if _validate_agent(name, stock_name):
                return name
    
    return None


def _validate_agent(agent: str, stock_name: str = None) -> bool:
    """Quality filter to reject garbage agent names."""
    if not agent:
        return False
    
    agent_lower = agent.lower().strip()
    
    # Length check
    if len(agent) < 6 or len(agent) > 100:
        return False
    
    # Must contain financial keyword
    if not any(kw in agent_lower for kw in [
        'securities', 'capital', 'finance', 'bank', 'asia', 'international',
        'partners', 'group', 'limited', 'ltd', 'investment', 'asset',
        'management', 'wealth', 'fund', 'broker', 'financial'
    ]):
        return False
    
    # Reject pure generic suffixes
    if agent_lower in ['securities limited', 'capital limited', 
                         'securities co., limited', 'securities (hong kong) limited']:
        return False
    
    # Reject garbage keywords
    garbage_kw = [
        'pursuant to', 'securities and futures', 'securities ordinance',
        'howsoever', 'reliance upon', 'disclaim any', 'whatsoever',
        'not limited to', 'general mandate', 'short position',
        'shares will be', 'the directors', 'the company', 'the board',
        'the group', 'the stock', 'the securities', 'the hong kong',
        'the listing', 'chapter', 'rule', 'appendix', 'section', 'part xiv',
        'ubscribe', 'ubscription',
    ]
    if any(kw in agent_lower for kw in garbage_kw):
        return False
    
    # Reject OCR sentence fragments
    sentence_starts = [
        'sole placing agent and', 'company placing agent',
        'placing agents and', 'company and',
    ]
    if any(agent_lower.startswith(s) for s in sentence_starts):
        return False
    
    # Not company's own name
    if stock_name and len(stock_name) > 3:
        if stock_name.lower() in agent_lower:
            return False
        # Chinese name fragments
        for part_len in [3, 4]:
            for start in range(0, max(1, len(stock_name) - part_len + 1)):
                frag = stock_name[start:start + part_len]
                if len(frag) >= 3 and frag in agent:
                    return False
    
    return True


def ocr_pdf_document(pdf_bytes: bytes, max_pages: int = 5) -> str:
    """OCR entire PDF document with Mistral (for corp action analysis).
    
    Uses Mistral's native PDF OCR endpoint for best results.
    
    Args:
        pdf_bytes: Raw PDF bytes
        max_pages: Max pages to process
    
    Returns full extracted text.
    """
    from mistralai.client import models
    
    client = _get_client()
    
    try:
        # Upload PDF to Mistral using the v2 files API
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name
        
        with open(tmp_path, 'rb') as f:
            file_content = f.read()
        
        uploaded = client.files.upload(
            file=models.File(
                file_name="document.pdf",
                content=file_content,
                content_type="application/pdf",
            ),
            purpose="ocr"
        )
        
        # Get signed URL and process with OCR
        signed_url = client.files.get_signed_url(file_id=uploaded.id)
        
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document=models.DocumentURLChunk(
                type="document_url",
                document_url=signed_url.url,
            ),
            include_image_base64=False,
        )
        
        # Extract text from OCR response pages
        text_parts = []
        for page in ocr_response.pages[:max_pages]:
            text_parts.append(page.markdown)
        
        os.unlink(tmp_path)
        return "\n\n".join(text_parts)
        
    except Exception as e:
        logger.error(f"Mistral document OCR failed: {e}")
        # Fallback: page-by-page image OCR
        logger.info("Falling back to page-by-page image OCR")
        texts = []
        for pg in range(max_pages):
            try:
                t = ocr_pdf_page(pdf_bytes, pg)
                if t:
                    texts.append(t)
            except Exception:
                pass
        return "\n\n".join(texts)


# Quick test
if __name__ == "__main__":
    print(f"Mistral OCR module loaded. Key present: {bool(_load_key())}")
