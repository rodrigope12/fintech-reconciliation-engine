
import re
from typing import Optional
import structlog
from ...integrations.google_vision import OCRPage
from .domain import ValidationContext
from .hypothesis import generate_isomorphic_variants # We will create this next

logger = structlog.get_logger()

class HeaderExtractor:
    """
    Extracts global boundary conditions (Start/End Balance) from the document headers/footers.
    """
    
    START_BALANCE_KEYWORDS = [
        "saldo anterior", "saldo inicial", "saldo al corte anterior", 
        "adeudo del periodo anterior", "adeudo anterior", "deuda anterior",
    ]
    END_BALANCE_KEYWORDS = [
        "saldo final", "nuevo saldo", "saldo al corte", "saldo actual", 
        "total a pagar", "pago para no generar intereses", "pago para no generar"
    ]

    def extract_context(self, pages: list[OCRPage]) -> Optional[ValidationContext]:
        """
        Scan pages to find start and end balances.
        Usually found on the first page.
        """
        start_bal = None
        end_bal = None
        
        if not pages:
            return None
            
        # Scan first few pages (summary is usually in page 1, 2 or 3)
        scan_limit = min(len(pages), 3)
        
        for i in range(scan_limit):
            page = pages[i]
            if start_bal is None:
                start_bal = self._find_balance(page, self.START_BALANCE_KEYWORDS)
            if end_bal is None:
                end_bal = self._find_balance(page, self.END_BALANCE_KEYWORDS)
                
            if start_bal is not None and end_bal is not None:
                break
        
        # If still missing end balance, try the very last page
        if end_bal is None and len(pages) > scan_limit:
            end_bal = self._find_balance(pages[-1], self.END_BALANCE_KEYWORDS)

        if start_bal is not None and end_bal is not None:
            logger.info("Extracted boundary conditions", start=start_bal, end=end_bal)
            return ValidationContext(start_balance_cents=start_bal, end_balance_cents=end_bal)
            
        logger.warning("Could not fully extract boundary conditions", start=start_bal, end=end_bal)
        return None

    def _find_balance(self, page: OCRPage, keywords: list[str]) -> Optional[int]:
        """
        Find a specific type of balance on the page.
        """
    def _find_balance(self, page: OCRPage, keywords: list[str]) -> Optional[int]:
        """
        Find a specific type of balance on the page.
        """
        for i, row in enumerate(page.rows):
            text_lower = row.raw_text.lower()
            # logger.debug("Scanning row for balance", text=text_lower) # Too noisy to enable by default
            for kw in keywords:
                if kw in text_lower:
                    nums = self._extract_numbers_from_row(row)
                    logger.info("Found balance keyword match", keyword=kw, text=row.raw_text, nums_found=nums)
                    
                    if not nums and i + 1 < len(page.rows):
                        # Try next row (multi-line header)
                        next_row = page.rows[i+1]
                        nums = self._extract_numbers_from_row(next_row)
                        logger.info("Checking next row for balance", next_row_text=next_row.raw_text, nums_found=nums)
                    
                    if nums:
                        # Heuristic: Balance is usually the first number immediately following the keyword.
                        # Using max(nums) caused errors when a larger unrelated number appeared later in the line.
                        return nums[0]
                        
        return None

    def extract_year(self, pages: list[OCRPage]) -> int:
        """
        Extract the statement year from the document.
        Defaults to current year if not found.
        """
        from datetime import date
        current_year = date.today().year
        found_years = []
        
        # Scan first few pages
        scan_limit = min(len(pages), 3)
        year_pattern = re.compile(r"\b(20\d{2})\b")
        
        for i in range(scan_limit):
            page = pages[i]
            for row in page.rows:
                text = row.raw_text
                # Look for 4 digit years starting with 20
                matches = year_pattern.findall(text)
                for m in matches:
                    y = int(m)
                    if 2000 <= y <= current_year + 1:
                        # Weight it higher if it's in a date context
                        weight = 1
                        if any(kw in text.lower() for kw in ["periodo", "fecha", "corte", "date", "year"]):
                            weight = 2
                        found_years.append((y, weight))
        
        if found_years:
            # Return the most frequent year, weighted
            from collections import Counter
            counts = Counter()
            for y, w in found_years:
                counts[y] += w
            
            # Get the year with max score
            # Tie breaker: prefer the larger year (latest)
            best_year = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)[0][0]
            logger.info("Detected statement year", year=best_year)
            return best_year
            
        logger.warning("Could not detect statement year, defaulting to current", year=current_year)
        return current_year

    def _extract_numbers_from_row(self, row) -> list[int]:
        nums = []
        for w in row.words:
            variants = generate_isomorphic_variants(w.text)
            if variants:
                val = variants[0].value_cents
                # Filter out likely credit card numbers (usually > 12 digits implies trillions of dollars)
                # 16 digits = 10^15. A balance of trillions is unlikely.
                # Threshold: 100 billion dollars (10^11 * 100 cents = 10^13)
                if val < 10**13: 
                    nums.append(val)
        return nums
