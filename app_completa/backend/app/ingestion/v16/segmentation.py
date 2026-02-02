
import re
from datetime import date, datetime
from typing import List, Tuple, Optional
import structlog

from ...integrations.google_vision import OCRPage, OCRRow, OCRWord
from .domain import TransactionBlock, IsomorphicVariant

logger = structlog.get_logger()

# Standard Mexican/International date patterns
DATE_PATTERNS = [
    re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})"),  # DD/MM/YYYY or DD-MM-YY or DD.MM.YYYY
    re.compile(r"(\d{1,2})[\s/\-.]+(ene|jan|feb|mar|abr|apr|may|jun|jul|ago|aug|sep|oct|nov|dic|dec)[\s/\-.]+(\d{2,4})", re.I), # DD-MMM-YYYY
    re.compile(r"(\d{1,2})[\s/\-.]+(ene|jan|feb|mar|abr|apr|may|jun|jul|ago|aug|sep|oct|nov|dic|dec)(?!\w)", re.I), # DD-MMM
]

MONTH_MAP = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

def parse_date_str(date_str: str, year_context: Optional[int] = None) -> Optional[date]:
    """Try to parse a date string using known patterns."""
    for pattern in DATE_PATTERNS:
        match = pattern.search(date_str)
        if match:
            try:
                groups = match.groups()
                day = int(groups[0])
                
                # Handle month
                month_str = groups[1].lower()
                if month_str.isdigit():
                    month = int(month_str)
                else:
                    month = MONTH_MAP.get(month_str[:3], 0)
                
                # Handle year
                if len(groups) > 2:
                    year_str = groups[2]
                    if len(year_str) == 2:
                        year = 2000 + int(year_str)
                    else:
                        year = int(year_str)
                else:
                    # Implied year
                    year = year_context or date.today().year

                return date(year, month, day)
            except (ValueError, IndexError):
                continue
    return None

def detect_dates(page: OCRPage, year_context: Optional[int] = None) -> List[Tuple[date, float]]:
    """
    Find all vertical date anchors in the page.
    Returns list of (date_obj, y_center_px).
    """
    found_dates = []
    
    # Iterate over words to find dates (could be split across words, but usually OCR keeps them together or we can check rows)
    # For robust V16, we check row by row. Each row that starts with a date is an anchor.
    
    for i, row in enumerate(page.rows):
        # Check first few words typical for a transaction start
        # Limit to left side of page (first 40% usually) for anchors
        left_words = [w for w in row.words if w.bounding_box["x"] < page.width * 0.4]
        
        # Try to form a date string from the first 6 tokens (increased scan depth)
        text_snippet = " ".join(w.text for w in left_words[:6])
        
        d = parse_date_str(text_snippet, year_context)
        if d:
            # Found a date anchor!
            y_center = row.y_position
            found_dates.append((d, y_center))
        elif i < 5: # Log first few rows to see what OCR sees
             logger.debug("Row failed date check", text=text_snippet)
            
    # Sort by Y position
    sorted_dates = sorted(found_dates, key=lambda x: x[1])
    logger.debug("Detected dates on page", count=len(sorted_dates), dates=[d.isoformat() for d, _ in sorted_dates])
    return sorted_dates

def create_transaction_blocks(page: OCRPage, dates: List[Tuple[date, float]]) -> List[TransactionBlock]:
    """
    Slice the page into vertical blocks based on date anchors.
    """
    blocks = []
    if not dates:
        return []
    
    for i, (anchor_date, y_start) in enumerate(dates):
        # Determine Y range
        y_next = dates[i+1][1] if i + 1 < len(dates) else page.height
        
        # Define a safety margin (don't overlap too much)
        # We assume a block extends from its date up to the next date
        y_end = y_next
        
        block = TransactionBlock(
            block_id=i,
            anchor_date=anchor_date,
        )
        
        # Collect all words in this vertical band
        # And populate candidates (amounts vs descriptions)
        populate_block_content(block, page, y_start, y_end)
        blocks.append(block)
        
    return blocks

def populate_block_content(block: TransactionBlock, page: OCRPage, y_min: float, y_max: float):
    """
    Filter words falling into the Y-range and classify them as text or number candidates.
    """
    # Strict tolerance: -5px (up) to allow slightly misaligned date, + full height down
    y_min_eff = y_min - 5
    y_max_eff = y_max - 2 
    
    words_in_block = []
    
    # Noise keywords to exclude
    NOISE_KEYWORDS = ["puntos", "points", "beneficios", "total", "abonos", "cargos", "resumen", "tipo de cambio"]
    
    for row in page.rows:
        text_lower = row.raw_text.lower()
        if any(kw in text_lower for kw in NOISE_KEYWORDS):
            continue
            
        if y_min_eff <= row.y_position < y_max_eff:
            words_in_block.extend(row.words)
            
    # Sort by X
    words_in_block.sort(key=lambda w: w.bounding_box['x'])
    
    # Heuristic for columns: 
    # Left side -> likely description
    # Right side -> likely amounts
    # We will refine 'IsomorphicVariant' generation here
    
    # Join text for description
    text_tokens = [w.text for w in words_in_block if not is_money_token(w.text)]
    block.description_lines.append(" ".join(text_tokens))

    # Identify numeric tokens for candidates
    for w in words_in_block:
        if is_money_token(w.text):
            variants = generate_isomorphic_variants(w.text)
            if variants:
                # Add to both debit and credit piles?
                # V16 Strategy: Add to candidate list. The solver decides if it's debit or credit.
                # For simplicity in 'domain.py', distinct lists exist.
                # We can add same variants to both lists if column is ambiguous.
                
                # Check column zone (Spatial Pruning Pilar)
                # Assume right 50% is amounts (increased from 40% to avoid description noise)
                if w.bounding_box['x'] > page.width * 0.5:
                    block.debit_candidates.append(variants)
                    block.credit_candidates.append(variants) 

def is_money_token(text: str) -> bool:
    """True if looks like a number candidate."""
    # Exclude masked card numbers e.g. ***9632 or **9096
    if "*" in text:
        return False
        
    # Check if it has digits
    if not any(c.isdigit() for c in text):
        return False

    # V16 Heuristic: Reject plain 4-digit integers (years, card tails)
    # real amounts usually have punctuation: 3,000.00 or 59.90
    clean_text = text.replace("$", "").replace(" ", "")
    if clean_text.isdigit() and len(clean_text) == 4:
        return False

    return True

from .hypothesis import generate_isomorphic_variants
