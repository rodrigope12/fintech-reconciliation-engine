"""
CFDI (Electronic Invoice) XML parser.
Extracts transaction data from Mexican electronic invoices.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any
from decimal import Decimal
import xml.etree.ElementTree as ET

import structlog

from ..models import CFDITransaction, TransactionType, MetodoPago, CommitStatus

logger = structlog.get_logger()


# XML Namespaces for CFDI 4.0 and 3.3
CFDI_NAMESPACES = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "cfdi33": "http://www.sat.gob.mx/cfd/3",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
    "pago20": "http://www.sat.gob.mx/Pagos20",
    "pago10": "http://www.sat.gob.mx/Pagos",
}


@dataclass
class CFDIParseResult:
    """Result of parsing a CFDI."""
    transaction: Optional[CFDITransaction]
    related_payments: List[Dict[str, Any]]
    errors: List[str]
    warnings: List[str]


class CFDIParser:
    """
    Parser for CFDI XML files.
    Supports CFDI 3.3 and 4.0 formats.
    """

    def parse_xml(
        self,
        xml_content: str,
        source_file: Optional[str] = None,
    ) -> CFDIParseResult:
        """
        Parse a CFDI XML string.

        Args:
            xml_content: XML content as string
            source_file: Optional source file path for tracking

        Returns:
            CFDIParseResult with extracted transaction
        """
        errors = []
        warnings = []
        related_payments = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error("Failed to parse CFDI XML", error=str(e))
            return CFDIParseResult(
                transaction=None,
                related_payments=[],
                errors=[f"XML parse error: {str(e)}"],
                warnings=[],
            )

        # Detect CFDI version
        version = root.get("Version") or root.get("version", "4.0")
        ns_prefix = "cfdi" if version.startswith("4") else "cfdi33"

        # Extract basic info
        try:
            txn = self._extract_transaction(root, ns_prefix, version, source_file)
        except Exception as e:
            logger.error("Failed to extract transaction", error=str(e))
            return CFDIParseResult(
                transaction=None,
                related_payments=[],
                errors=[f"Extraction error: {str(e)}"],
                warnings=[],
            )

        # Check for payment complement (Complemento de Pago)
        if txn.cfdi_tipo == "P":
            related_payments = self._extract_payment_complement(root)
            txn.es_complemento_pago = True
            txn.doctos_relacionados = [p["uuid"] for p in related_payments if p.get("uuid")]

        return CFDIParseResult(
            transaction=txn,
            related_payments=related_payments,
            errors=errors,
            warnings=warnings,
        )

    def _extract_transaction(
        self,
        root: ET.Element,
        ns_prefix: str,
        version: str,
        source_file: Optional[str],
    ) -> CFDITransaction:
        """Extract transaction data from CFDI XML."""
        ns = CFDI_NAMESPACES

        # Get CFDI type
        tipo = root.get("TipoDeComprobante", "I")

        # Get amounts
        total = self._parse_decimal(root.get("Total", "0"))
        subtotal = self._parse_decimal(root.get("SubTotal", "0"))
        descuento = self._parse_decimal(root.get("Descuento", "0"))

        # Get dates
        fecha_str = root.get("Fecha", "")
        fecha_emision = self._parse_datetime(fecha_str)

        # Get currency
        moneda = root.get("Moneda", "MXN")
        tipo_cambio = self._parse_decimal(root.get("TipoCambio", "1"))

        # Get payment info
        metodo_pago_str = root.get("MetodoPago", "")
        metodo_pago = None
        if metodo_pago_str:
            try:
                metodo_pago = MetodoPago(metodo_pago_str)
            except ValueError:
                pass

        forma_pago = root.get("FormaPago", "")

        # Get Emisor (issuer)
        emisor = root.find(f".//{ns_prefix}:Emisor", ns) or root.find(".//Emisor")
        emisor_rfc = emisor.get("Rfc", "") if emisor is not None else ""
        emisor_nombre = emisor.get("Nombre", "") if emisor is not None else ""

        # Get Receptor (recipient)
        receptor = root.find(f".//{ns_prefix}:Receptor", ns) or root.find(".//Receptor")
        receptor_rfc = receptor.get("Rfc", "") if receptor is not None else ""
        receptor_nombre = receptor.get("Nombre", "") if receptor is not None else ""

        # Get UUID from TimbreFiscalDigital
        tfd = root.find(".//tfd:TimbreFiscalDigital", ns)
        if tfd is None:
            # Try without namespace
            for elem in root.iter():
                if "TimbreFiscalDigital" in elem.tag:
                    tfd = elem
                    break

        uuid = tfd.get("UUID", "") if tfd is not None else ""
        fecha_timbrado = None
        if tfd is not None:
            fecha_timbrado = self._parse_datetime(tfd.get("FechaTimbrado", ""))

        # Get Conceptos (line items)
        conceptos = self._extract_conceptos(root, ns_prefix)

        # Determine transaction type
        # I = Ingreso (income/sale), E = Egreso (expense/refund), P = Pago (payment)
        txn_type = TransactionType.CREDIT if tipo in ("I", "P") else TransactionType.DEBIT

        # Convert to cents
        total_cents = int(total * 100)
        subtotal_cents = int(subtotal * 100)
        descuento_cents = int(descuento * 100)

        return CFDITransaction(
            external_id=uuid,
            cfdi_uuid=uuid,
            cfdi_version=version,
            cfdi_tipo=tipo,
            source_file=source_file,
            amount_cents=total_cents,
            currency=moneda,
            transaction_type=txn_type,
            transaction_date=fecha_emision.date() if fecha_emision else None,
            fecha_emision=fecha_emision,
            fecha_timbrado=fecha_timbrado,
            counterparty_name=receptor_nombre if tipo == "I" else emisor_nombre,
            counterparty_rfc=receptor_rfc if tipo == "I" else emisor_rfc,
            emisor_rfc=emisor_rfc,
            emisor_nombre=emisor_nombre,
            receptor_rfc=receptor_rfc,
            receptor_nombre=receptor_nombre,
            subtotal_cents=subtotal_cents,
            total_impuestos_cents=total_cents - subtotal_cents + descuento_cents,
            descuento_cents=descuento_cents,
            metodo_pago=metodo_pago,
            forma_pago=forma_pago,
            description=self._build_description(conceptos),
            conceptos=conceptos,
            commit_status=CommitStatus.PENDING,
            ocr_confidence=1.0,  # XMLs are exact, no OCR
        )

    def _extract_conceptos(
        self,
        root: ET.Element,
        ns_prefix: str,
    ) -> List[Dict[str, Any]]:
        """Extract line items from CFDI."""
        ns = CFDI_NAMESPACES
        conceptos = []

        conceptos_elem = root.find(f".//{ns_prefix}:Conceptos", ns) or root.find(".//Conceptos")
        if conceptos_elem is None:
            return conceptos

        for concepto in conceptos_elem:
            if "Concepto" not in concepto.tag:
                continue

            conceptos.append({
                "clave_prod_serv": concepto.get("ClaveProdServ", ""),
                "cantidad": self._parse_decimal(concepto.get("Cantidad", "1")),
                "clave_unidad": concepto.get("ClaveUnidad", ""),
                "unidad": concepto.get("Unidad", ""),
                "descripcion": concepto.get("Descripcion", ""),
                "valor_unitario": self._parse_decimal(concepto.get("ValorUnitario", "0")),
                "importe": self._parse_decimal(concepto.get("Importe", "0")),
                "descuento": self._parse_decimal(concepto.get("Descuento", "0")),
            })

        return conceptos

    def _extract_payment_complement(
        self,
        root: ET.Element,
    ) -> List[Dict[str, Any]]:
        """
        Extract related documents from payment complement (Complemento de Pago).
        """
        ns = CFDI_NAMESPACES
        related = []

        # Try Pagos 2.0
        pagos = root.find(".//pago20:Pagos", ns)
        if pagos is None:
            # Try Pagos 1.0
            pagos = root.find(".//pago10:Pagos", ns)

        if pagos is None:
            return related

        for pago in pagos:
            if "Pago" not in pago.tag:
                continue

            # Get payment info
            fecha_pago = pago.get("FechaPago", "")
            monto = self._parse_decimal(pago.get("Monto", "0"))

            # Get related documents
            for docto in pago:
                if "DoctoRelacionado" not in docto.tag:
                    continue

                related.append({
                    "uuid": docto.get("IdDocumento", ""),
                    "serie": docto.get("Serie", ""),
                    "folio": docto.get("Folio", ""),
                    "moneda": docto.get("MonedaDR", "MXN"),
                    "num_parcialidad": docto.get("NumParcialidad", "1"),
                    "imp_saldo_ant": self._parse_decimal(docto.get("ImpSaldoAnt", "0")),
                    "imp_pagado": self._parse_decimal(docto.get("ImpPagado", "0")),
                    "imp_saldo_insoluto": self._parse_decimal(docto.get("ImpSaldoInsoluto", "0")),
                    "fecha_pago": fecha_pago,
                })

        return related

    def _build_description(self, conceptos: List[Dict[str, Any]]) -> str:
        """Build description from line items."""
        if not conceptos:
            return ""

        descriptions = [c.get("descripcion", "") for c in conceptos if c.get("descripcion")]
        return " | ".join(descriptions[:3])  # Limit to first 3 items

    def _parse_decimal(self, value: str) -> Decimal:
        """Parse string to Decimal, defaulting to 0."""
        try:
            return Decimal(value.replace(",", "")) if value else Decimal("0")
        except Exception:
            return Decimal("0")

    def _parse_datetime(self, value: str) -> Optional[datetime]:
        """Parse datetime string."""
        if not value:
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        return None

    def parse_multiple(
        self,
        xml_contents: List[str],
    ) -> List[CFDIParseResult]:
        """Parse multiple CFDI XMLs."""
        results = []
        for i, xml in enumerate(xml_contents):
            result = self.parse_xml(xml, source_file=f"cfdi_{i}.xml")
            results.append(result)
        return results
