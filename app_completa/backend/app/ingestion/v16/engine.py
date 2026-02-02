
from typing import List, Tuple, Optional
import structlog

from ...models import BankTransaction, TransactionType, CommitStatus
from ...integrations.google_vision import OCRDocument
from .domain import TransactionBlock, ValidationContext
from .segmentation import detect_dates, create_transaction_blocks
from .header_extractor import HeaderExtractor
from .solver import CSPSolver

logger = structlog.get_logger()

class V16BankParserEngine:
    """
    Orchestrates the V16.0 Global Constraint Solver pipeline.
    """
    
    def __init__(self):
        self.header_extractor = HeaderExtractor()
        self.solver = CSPSolver(tolerance_cents=100) # 1 peso tolerance for global equation

    def process(self, ocr_doc: OCRDocument) -> Tuple[List[BankTransaction], Optional[ValidationContext]]:
        """
        Main entry point.
        """
        logger.info("Starting V16 Engine processing", pages=ocr_doc.total_pages)
        
        # 1. Extract Boundary Conditions (Start/End Balance)
        context = self.header_extractor.extract_context(ocr_doc.pages)
        if not context:
            logger.error("V16 Failed: Could not determine start/end balances from document.")
            # Fallback or empty result?
            # V16 is strict. If no context, we can't solve.
            return [], None

        # 2. Extract Year Context
        year_context = self.header_extractor.extract_year(ocr_doc.pages)
        logger.info("Using year context", year=year_context)

        # 3. Global Segmentation (All pages treated as one time series)
        all_blocks = []
        block_offset_id = 0
        
        for page in ocr_doc.pages:
            # Detect dates with context
            dates = detect_dates(page, year_context=year_context)
            # Create blocks
            blocks = create_transaction_blocks(page, dates)
            
            # Update block IDs to be globally unique
            for b in blocks:
                b.block_id += block_offset_id
            
            all_blocks.extend(blocks)
            if blocks:
                block_offset_id += len(blocks)
        
        if not all_blocks:
            logger.warning("V16 Warning: No transaction blocks found (no dates detected).")
            return [], context

        # 4. Solve CSP
        # We try to solve the whole document at once
        solved = self.solver.solve(context, all_blocks)
        
        if not solved:
            logger.error("V16 Failed: No mathematical solution found for global balance equation.")
            return [], context
            
        # 4. Convert Solution to BankTransaction objects
        transactions = self._blocks_to_transactions(all_blocks, context.start_balance_cents, ocr_doc.file_path)
        
        logger.info("V16 Success", transactions=len(transactions))
        return transactions, context

    def _blocks_to_transactions(self, 
                                blocks: List[TransactionBlock], 
                                start_balance: int,
                                source_file: str) -> List[BankTransaction]:
        
        transactions = []
        current_balance = start_balance
        
        for block in blocks:
            # Skip if noise (no selection)
            if not block.selected_debit and not block.selected_credit:
                continue
                
            amount_cents = 0
            txn_type = TransactionType.DEBIT
            
            if block.selected_debit:
                amount_cents = block.selected_debit.value_cents
                txn_type = TransactionType.DEBIT
                current_balance -= amount_cents
                raw_text = block.selected_debit.original_text
                
            elif block.selected_credit:
                amount_cents = block.selected_credit.value_cents
                txn_type = TransactionType.CREDIT
                current_balance += amount_cents
                raw_text = block.selected_credit.original_text
            
            # Construct Description
            desc = " ".join(block.description_lines).strip()
            if not desc:
                desc = "DESCRIPCION NO LEIDA"
                
            txn = BankTransaction(
                source_file=source_file,
                source_page=1, # We lost page tracking in blocks, simpler to verify logic first
                source_row=block.block_id,
                amount_cents=amount_cents,
                transaction_type=txn_type,
                transaction_date=block.anchor_date,
                description=desc,
                balance_before_cents=0, # Calculated afterwards implies order
                balance_after_cents=current_balance,
                ocr_raw_text=raw_text,
                ocr_confidence=0.99, # V16 implies truth
                commit_status=CommitStatus.PENDING,
            )
            # Fix balance before
            if txn_type == TransactionType.DEBIT:
                txn.balance_before_cents = txn.balance_after_cents + amount_cents
            else:
                txn.balance_before_cents = txn.balance_after_cents - amount_cents
                
            transactions.append(txn)
            
        return transactions
