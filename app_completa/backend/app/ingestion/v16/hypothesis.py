
from typing import List
from .domain import IsomorphicVariant

def generate_isomorphic_variants(raw_text: str) -> List[IsomorphicVariant]:
    """
    Generate valid numeric interpretations (e.g. '1,000.00' -> 100000).
    Handles commas, dots, OCR noise (l -> 1, O -> 0).
    """
    variants = []
    
    # 1. Standard cleaner
    clean = raw_text.replace('$', '').replace(' ', '')
    if not clean:
        return []
    
    # Variant A: Standard (commas for thousands, dot for decimal)
    try:
        val_str = clean.replace(',', '')
        val_float = float(val_str)
        val_cents = int(round(val_float * 100))
        variants.append(IsomorphicVariant(val_cents, 0.9, 'standard', raw_text))
    except ValueError:
        pass
        
    # Variant B: Swap dot/comma (European style or typo)
    try:
        # Check if it looks like european (dots as thousands)
        # 1.234,56
        if '.' in clean and ',' in clean and clean.find('.') < clean.find(','):
             val_str = clean.replace('.', '').replace(',', '.')
             val_float = float(val_str)
             val_cents = int(round(val_float * 100))
             variants.append(IsomorphicVariant(val_cents, 0.8, 'swap_separators', raw_text))
    except ValueError:
        pass

    # Variant C: OCR Fixes (l->1, O->0, S->5)
    clean_ocr = clean.translate(str.maketrans('lOSs', '1055'))
    if clean_ocr != clean:
        try:
            val_str = clean_ocr.replace(',', '')
            val_float = float(val_str)
            val_cents = int(round(val_float * 100))
            variants.append(IsomorphicVariant(val_cents, 0.7, 'ocr_fix', raw_text))
        except ValueError:
            pass
            
    # Variant D: Missing decimal point assumption (if large number ending in 00 without dot)
    # e.g. "10000" read as 10000 instead of 100.00? Usually not safe, but can add with low confidence.
    
    return variants
