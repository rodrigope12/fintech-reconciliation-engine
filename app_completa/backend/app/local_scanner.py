"""
Local folder scanner for PDF and CFDI files.
Scans local directories for client subfolders.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import structlog

logger = structlog.get_logger()


@dataclass
class ClientFolder:
    """Represents a client folder with files."""
    name: str
    path: Path
    file_count: int
    files: List[str] = field(default_factory=list)
    size_mb: float = 0.0


@dataclass
class ScanResult:
    """Result of scanning local folders."""
    pdf_clients: List[ClientFolder]
    cfdi_clients: List[ClientFolder]
    warnings: List[str]
    errors: List[str]
    matched_clients: List[str]  # Clients present in both folders
    pdf_only_clients: List[str]  # Clients only in PDF folder
    cfdi_only_clients: List[str]  # Clients only in CFDI folder


class LocalFolderScanner:
    """
    Scanner for local PDF and CFDI folders.

    Expected structure:
    /pdf/
        Cliente_A/
            estado_cuenta_enero.pdf
            estado_cuenta_febrero.pdf
        Cliente_B/
            ...
    /CFDI/
        Cliente_A/
            factura_001.xml
            factura_002.xml
        Cliente_B/
            ...
    """

    def __init__(
        self,
        base_path: Optional[str] = None,
        pdf_folder_name: str = "pdf",
        cfdi_folder_name: str = "CFDI",
    ):
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.pdf_folder = self.base_path / pdf_folder_name
        self.cfdi_folder = self.base_path / cfdi_folder_name

    def validate_structure(self) -> Tuple[bool, List[str]]:
        """
        Validate that required folder structure exists.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        if not self.base_path.exists():
            errors.append(f"Base path does not exist: {self.base_path}")

        if not self.pdf_folder.exists():
            errors.append(
                f"PDF folder not found: {self.pdf_folder}\n"
                f"Please create the folder and add client subfolders with PDF files."
            )

        if not self.cfdi_folder.exists():
            errors.append(
                f"CFDI folder not found: {self.cfdi_folder}\n"
                f"Please create the folder and add client subfolders with XML files."
            )

        return len(errors) == 0, errors

    def scan_all(self) -> ScanResult:
        """
        Scan both PDF and CFDI folders for client subfolders.

        Returns:
            ScanResult with all client folders and validation info
        """
        warnings = []
        errors = []

        # Validate structure first
        is_valid, structure_errors = self.validate_structure()
        if not is_valid:
            return ScanResult(
                pdf_clients=[],
                cfdi_clients=[],
                warnings=[],
                errors=structure_errors,
                matched_clients=[],
                pdf_only_clients=[],
                cfdi_only_clients=[],
            )

        # Scan PDF folder
        pdf_clients = self._scan_folder(self.pdf_folder, [".pdf"])

        # Scan CFDI folder
        cfdi_clients = self._scan_folder(self.cfdi_folder, [".xml"])

        # Compare client lists
        pdf_names = {c.name.lower(): c.name for c in pdf_clients}
        cfdi_names = {c.name.lower(): c.name for c in cfdi_clients}

        matched = []
        pdf_only = []
        cfdi_only = []

        for name_lower, name in pdf_names.items():
            if name_lower in cfdi_names:
                matched.append(name)
            else:
                pdf_only.append(name)
                warnings.append(
                    f"Client '{name}' has PDFs but no CFDIs folder"
                )

        for name_lower, name in cfdi_names.items():
            if name_lower not in pdf_names:
                cfdi_only.append(name)
                warnings.append(
                    f"Client '{name}' has CFDIs but no PDF folder"
                )

        logger.info(
            "Folder scan complete",
            pdf_clients=len(pdf_clients),
            cfdi_clients=len(cfdi_clients),
            matched=len(matched),
        )

        return ScanResult(
            pdf_clients=pdf_clients,
            cfdi_clients=cfdi_clients,
            warnings=warnings,
            errors=errors,
            matched_clients=matched,
            pdf_only_clients=pdf_only,
            cfdi_only_clients=cfdi_only,
        )

    def _scan_folder(
        self,
        folder: Path,
        extensions: List[str],
    ) -> List[ClientFolder]:
        """Scan a folder for client subfolders."""
        clients = []

        if not folder.exists():
            return clients

        for item in folder.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                # Count files with matching extensions
                files = []
                total_size = 0

                for file in item.iterdir():
                    if file.is_file() and file.suffix.lower() in extensions:
                        files.append(file.name)
                        total_size += file.stat().st_size

                if files:
                    clients.append(ClientFolder(
                        name=item.name,
                        path=item,
                        file_count=len(files),
                        files=sorted(files),
                        size_mb=total_size / (1024 * 1024),
                    ))

        # Sort by name
        clients.sort(key=lambda c: c.name.lower())
        return clients

    def get_pdf_files(self, client_name: str) -> List[Path]:
        """Get all PDF files for a client."""
        client_path = self.pdf_folder / client_name
        if not client_path.exists():
            return []

        return sorted([
            f for f in client_path.iterdir()
            if f.is_file() and f.suffix.lower() == ".pdf"
        ])

    def get_cfdi_files(self, client_name: str) -> List[Path]:
        """Get all CFDI XML files for a client."""
        client_path = self.cfdi_folder / client_name
        if not client_path.exists():
            return []

        return sorted([
            f for f in client_path.iterdir()
            if f.is_file() and f.suffix.lower() == ".xml"
        ])


def validate_google_credentials(credentials_path: str) -> Tuple[bool, str]:
    """
    Validate Google Cloud Vision API credentials file.

    Returns:
        Tuple of (is_valid, message)
    """
    cred_path = Path(credentials_path)

    if not cred_path.exists():
        return False, (
            f"Google Cloud Vision credentials not found at:\n"
            f"{credentials_path}\n\n"
            f"Please place your 'clave_API_cloud_vision.json' file in the app folder."
        )

    # Try to parse JSON
    try:
        import json
        with open(cred_path) as f:
            data = json.load(f)

        required_fields = ["type", "project_id", "private_key_id", "private_key"]
        missing = [f for f in required_fields if f not in data]

        if missing:
            return False, (
                f"Invalid credentials file. Missing fields: {', '.join(missing)}\n"
                f"Please ensure you have a valid service account JSON file."
            )

        return True, f"Credentials valid for project: {data.get('project_id', 'unknown')}"

    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in credentials file: {str(e)}"
    except Exception as e:
        return False, f"Error reading credentials: {str(e)}"
