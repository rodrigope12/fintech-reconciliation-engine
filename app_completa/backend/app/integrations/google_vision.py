"""
Google Cloud Vision API client for OCR processing of bank statements.
"""

import base64
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import structlog
from google.cloud import vision
from google.oauth2 import service_account
from PIL import Image
import fitz  # PyMuPDF

from ..config import get_settings

logger = structlog.get_logger()


@dataclass
class OCRWord:
    """A single word extracted by OCR with position and confidence."""
    text: str
    confidence: float
    bounding_box: Dict[str, float]  # x, y, width, height
    page: int
    row_estimate: int  # Estimated row based on y-coordinate


@dataclass
class OCRRow:
    """A row of text extracted from OCR."""
    words: List[OCRWord]
    page: int
    row_number: int
    y_position: float
    raw_text: str

    @property
    def avg_confidence(self) -> float:
        if not self.words:
            return 0.0
        return sum(w.confidence for w in self.words) / len(self.words)


@dataclass
class OCRPage:
    """A page of OCR results."""
    page_number: int
    rows: List[OCRRow]
    width: int
    height: int
    raw_text: str


@dataclass
class OCRDocument:
    """Complete OCR result for a document."""
    file_path: str
    pages: List[OCRPage]
    total_pages: int


class GoogleVisionClient:
    """
    Client for Google Cloud Vision API.
    Handles PDF to image conversion and OCR extraction.
    """

    def __init__(self):
        self.settings = get_settings()
        self.client = self._initialize_client()

    def _initialize_client(self) -> vision.ImageAnnotatorClient:
        """Initialize Google Vision client with credentials."""
        import os

        # Option 1: Service account file from settings
        if self.settings.google_application_credentials:
            logger.info("Using credentials from settings", path=self.settings.google_application_credentials)
            credentials = service_account.Credentials.from_service_account_file(
                self.settings.google_application_credentials
            )
            return vision.ImageAnnotatorClient(credentials=credentials)

        # Option 2: Base64 encoded credentials
        if self.settings.google_credentials_base64:
            logger.info("Using base64 credentials")
            credentials_json = base64.b64decode(
                self.settings.google_credentials_base64
            ).decode("utf-8")
            credentials_info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info
            )
            return vision.ImageAnnotatorClient(credentials=credentials)

        # Option 3: Look for credentials in CONCILIACION_BASE_PATH
        base_path = os.environ.get("CONCILIACION_BASE_PATH", os.path.expanduser("~/Documents/conciliacion"))
        creds_path = os.path.join(base_path, "clave_API_cloud_vision.json")
        if os.path.exists(creds_path):
            logger.info("Using credentials from app folder", path=creds_path)
            credentials = service_account.Credentials.from_service_account_file(creds_path)
            return vision.ImageAnnotatorClient(credentials=credentials)

        # Option 4: Environment variable GOOGLE_APPLICATION_CREDENTIALS
        env_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if env_creds and os.path.exists(env_creds):
            logger.info("Using credentials from GOOGLE_APPLICATION_CREDENTIALS", path=env_creds)
            credentials = service_account.Credentials.from_service_account_file(env_creds)
            return vision.ImageAnnotatorClient(credentials=credentials)

        # Option 5: Default credentials (from ADC)
        logger.warning("Using default Application Default Credentials - may not work correctly")
        return vision.ImageAnnotatorClient()

    def process_pdf(
        self,
        pdf_path: str,
        dpi: int = 300,
    ) -> OCRDocument:
        """
        Process a PDF file and extract text using OCR.
        Optimized to process page-by-page to reduce memory usage.

        Args:
            pdf_path: Path to the PDF file
            dpi: Resolution for PDF to image conversion

        Returns:
            OCRDocument with extracted text and positions
        """
        logger.info("Processing PDF with OCR", path=pdf_path)

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        pages = []
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        try:
            for page_num in range(total_pages):
                page = doc[page_num]
                
                # Render page to pixmap
                zoom = dpi / 72
                matrix = fitz.Matrix(zoom, zoom)
                pixmap = page.get_pixmap(matrix=matrix)

                # Convert to PIL Image
                # We do this one by one to save memory
                img = Image.frombytes(
                    "RGB",
                    [pixmap.width, pixmap.height],
                    pixmap.samples,
                )

                logger.debug("Processing page", page=page_num + 1, total=total_pages)
                ocr_page = self._process_image(img, page_num + 1)
                pages.append(ocr_page)
                
                # Explicitly release image memory
                del img
                del pixmap

        finally:
            doc.close()

        return OCRDocument(
            file_path=str(pdf_path),
            pages=pages,
            total_pages=len(pages),
        )

    def _process_image(
        self,
        image: Image.Image,
        page_number: int,
    ) -> OCRPage:
        """Process a single image with Google Vision OCR."""
        # Convert PIL Image to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format="PNG")
        img_bytes = img_byte_arr.getvalue()

        # Create Vision API image
        vision_image = vision.Image(content=img_bytes)

        try:
            # Perform document text detection (better for structured docs)
            response = self.client.document_text_detection(image=vision_image)
        except Exception as e:
            # Catch gRPC or other transport errors
            raise Exception(f"Vision API request failed: {str(e)}")

        if response.error.message:
            raise Exception(f"Vision API parsing error: {response.error.message}")

        # Parse response into structured format
        words = self._parse_response(response, page_number)
        rows = self._group_into_rows(words, image.height)

        # Get raw text
        raw_text = ""
        if response.full_text_annotation:
            raw_text = response.full_text_annotation.text

        return OCRPage(
            page_number=page_number,
            rows=rows,
            width=image.width,
            height=image.height,
            raw_text=raw_text,
        )

    def _parse_response(
        self,
        response: vision.AnnotateImageResponse,
        page_number: int,
    ) -> List[OCRWord]:
        """Parse Vision API response into OCRWord objects."""
        words = []

        if not response.full_text_annotation:
            return words

        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        # Get word text
                        word_text = "".join(
                            symbol.text for symbol in word.symbols
                        )

                        # Get confidence
                        confidence = word.confidence

                        # Get bounding box
                        vertices = word.bounding_box.vertices
                        x_coords = [v.x for v in vertices]
                        y_coords = [v.y for v in vertices]

                        bbox = {
                            "x": min(x_coords),
                            "y": min(y_coords),
                            "width": max(x_coords) - min(x_coords),
                            "height": max(y_coords) - min(y_coords),
                        }

                        words.append(OCRWord(
                            text=word_text,
                            confidence=confidence,
                            bounding_box=bbox,
                            page=page_number,
                            row_estimate=0,  # Will be set during grouping
                        ))

        return words

    def _group_into_rows(
        self,
        words: List[OCRWord],
        page_height: int,
        row_tolerance: float = 0.02,
    ) -> List[OCRRow]:
        """
        Group words into rows based on y-coordinate proximity.

        Args:
            words: List of OCR words
            page_height: Height of the page in pixels
            row_tolerance: Tolerance for considering words on same row (% of page height)
        """
        if not words:
            return []

        # Sort words by y position
        sorted_words = sorted(words, key=lambda w: w.bounding_box["y"])

        # Group into rows
        rows = []
        current_row_words = []
        current_y = None
        tolerance_px = page_height * row_tolerance

        for word in sorted_words:
            word_y = word.bounding_box["y"]

            if current_y is None:
                current_y = word_y
                current_row_words = [word]
            elif abs(word_y - current_y) <= tolerance_px:
                # Same row
                current_row_words.append(word)
            else:
                # New row - save current and start new
                if current_row_words:
                    row = self._create_row(current_row_words, len(rows))
                    rows.append(row)
                current_y = word_y
                current_row_words = [word]

        # Don't forget last row
        if current_row_words:
            row = self._create_row(current_row_words, len(rows))
            rows.append(row)

        return rows

    def _create_row(
        self,
        words: List[OCRWord],
        row_number: int,
    ) -> OCRRow:
        """Create an OCRRow from a list of words."""
        # Sort words by x position (left to right)
        sorted_words = sorted(words, key=lambda w: w.bounding_box["x"])

        # Update row estimate for each word
        for word in sorted_words:
            word.row_estimate = row_number

        # Calculate average y position
        avg_y = sum(w.bounding_box["y"] for w in sorted_words) / len(sorted_words)

        # Create raw text
        raw_text = " ".join(w.text for w in sorted_words)

        return OCRRow(
            words=sorted_words,
            page=sorted_words[0].page,
            row_number=row_number,
            y_position=avg_y,
            raw_text=raw_text,
        )

    def extract_table_data(
        self,
        ocr_page: OCRPage,
        column_boundaries: Optional[List[float]] = None,
    ) -> List[List[str]]:
        """
        Extract tabular data from an OCR page.

        Args:
            ocr_page: OCR results for a page
            column_boundaries: Optional x-coordinates defining column boundaries

        Returns:
            List of rows, each containing list of cell values
        """
        table_data = []

        for row in ocr_page.rows:
            if column_boundaries:
                # Split words into columns based on boundaries
                cells = self._split_by_columns(row.words, column_boundaries)
            else:
                # Auto-detect columns based on whitespace gaps
                cells = self._auto_detect_columns(row.words)

            table_data.append(cells)

        return table_data

    def _split_by_columns(
        self,
        words: List[OCRWord],
        boundaries: List[float],
    ) -> List[str]:
        """Split words into columns based on x-coordinate boundaries."""
        cells = [""] * (len(boundaries) + 1)

        for word in words:
            word_center = word.bounding_box["x"] + word.bounding_box["width"] / 2

            # Find which column this word belongs to
            col_idx = 0
            for i, boundary in enumerate(boundaries):
                if word_center < boundary:
                    break
                col_idx = i + 1

            # Append to cell
            if cells[col_idx]:
                cells[col_idx] += " " + word.text
            else:
                cells[col_idx] = word.text

        return cells

    def _auto_detect_columns(
        self,
        words: List[OCRWord],
        min_gap_ratio: float = 0.03,
    ) -> List[str]:
        """Auto-detect columns based on whitespace gaps between words."""
        if not words:
            return []

        if len(words) == 1:
            return [words[0].text]

        # Sort by x position
        sorted_words = sorted(words, key=lambda w: w.bounding_box["x"])

        # Find gaps between consecutive words
        cells = []
        current_cell = sorted_words[0].text
        page_width = max(w.bounding_box["x"] + w.bounding_box["width"] for w in words)
        min_gap = page_width * min_gap_ratio

        for i in range(1, len(sorted_words)):
            prev_word = sorted_words[i - 1]
            curr_word = sorted_words[i]

            prev_end = prev_word.bounding_box["x"] + prev_word.bounding_box["width"]
            curr_start = curr_word.bounding_box["x"]
            gap = curr_start - prev_end

            if gap > min_gap:
                # New column
                cells.append(current_cell)
                current_cell = curr_word.text
            else:
                # Same column
                current_cell += " " + curr_word.text

        cells.append(current_cell)
        return cells
