"""
Facturama API client for downloading CFDIs (electronic invoices).
"""

import base64
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import get_settings

logger = structlog.get_logger()


@dataclass
class CFDIMetadata:
    """Metadata for a CFDI from Facturama."""
    uuid: str
    folio: Optional[str]
    serie: Optional[str]
    fecha_emision: datetime
    tipo: str  # I=Ingreso, E=Egreso, P=Pago
    total: float
    subtotal: float
    descuento: float
    moneda: str
    tipo_cambio: float
    metodo_pago: Optional[str]
    forma_pago: Optional[str]

    # Emisor
    emisor_rfc: str
    emisor_nombre: str

    # Receptor
    receptor_rfc: str
    receptor_nombre: str

    # Status
    cancelado: bool
    fecha_cancelacion: Optional[datetime]


class FacturamaError(Exception):
    """Custom exception for Facturama API errors."""
    def __init__(self, message: str, status_code: int = 0, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class FacturamaClient:
    """
    Client for Facturama API.
    Handles authentication and CFDI downloads.
    """

    def __init__(
        self,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.settings = get_settings()
        self.base_url = self.settings.facturama_api_url
        self.user = user or self.settings.facturama_user
        self.password = password or self.settings.facturama_password
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def auth_header(self) -> str:
        """Generate Basic Auth header."""
        credentials = f"{self.user}:{self.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": self.auth_header,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make an authenticated request to Facturama API."""
        client = await self._get_client()

        try:
            response = await client.request(method, endpoint, **kwargs)

            if response.status_code == 401:
                raise FacturamaError(
                    "Authentication failed. Check RFC and password.",
                    status_code=401,
                )

            if response.status_code == 404:
                raise FacturamaError(
                    f"Resource not found: {endpoint}",
                    status_code=404,
                )

            if response.status_code >= 400:
                error_detail = response.text
                try:
                    error_detail = response.json()
                except Exception:
                    pass
                raise FacturamaError(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                    details=error_detail,
                )

            if response.status_code == 204:
                return {}

            return response.json()

        except httpx.TimeoutException:
            raise FacturamaError("Request timeout")
        except httpx.RequestError as e:
            raise FacturamaError(f"Request error: {str(e)}")

    async def validate_credentials(self) -> bool:
        """
        Validate Facturama credentials.

        Returns:
            True if credentials are valid
        """
        try:
            await self._request("GET", "/api/Profile")
            logger.info("Facturama credentials validated")
            return True
        except FacturamaError as e:
            if e.status_code == 401:
                logger.warning("Invalid Facturama credentials")
                return False
            raise

    async def get_profile(self) -> Dict[str, Any]:
        """Get account profile information."""
        return await self._request("GET", "/api/Profile")

    async def list_cfdis_issued(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        tipo: Optional[str] = None,
        folio: Optional[str] = None,
        rfc_receptor: Optional[str] = None,
    ) -> List[CFDIMetadata]:
        """
        List CFDIs issued by the account.

        Args:
            start_date: Filter by start date
            end_date: Filter by end date
            tipo: Filter by type (I, E, P)
            folio: Filter by folio
            rfc_receptor: Filter by receptor RFC

        Returns:
            List of CFDI metadata
        """
        params = {}

        if start_date:
            params["fechaInicio"] = start_date.isoformat()
        if end_date:
            params["fechaFin"] = end_date.isoformat()
        if tipo:
            params["tipo"] = tipo
        if folio:
            params["folio"] = folio
        if rfc_receptor:
            params["rfcReceptor"] = rfc_receptor

        response = await self._request(
            "GET",
            "/api/Cfdi",
            params=params,
        )

        return [self._parse_cfdi_metadata(cfdi) for cfdi in response]

    async def list_cfdis_received(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        tipo: Optional[str] = None,
        rfc_emisor: Optional[str] = None,
    ) -> List[CFDIMetadata]:
        """
        List CFDIs received by the account.

        Args:
            start_date: Filter by start date
            end_date: Filter by end date
            tipo: Filter by type (I, E, P)
            rfc_emisor: Filter by emisor RFC

        Returns:
            List of CFDI metadata
        """
        params = {}

        if start_date:
            params["fechaInicio"] = start_date.isoformat()
        if end_date:
            params["fechaFin"] = end_date.isoformat()
        if tipo:
            params["tipo"] = tipo
        if rfc_emisor:
            params["rfcEmisor"] = rfc_emisor

        response = await self._request(
            "GET",
            "/api/Cfdi/Received",
            params=params,
        )

        return [self._parse_cfdi_metadata(cfdi) for cfdi in response]

    async def download_cfdi_xml(self, cfdi_id: str) -> str:
        """
        Download CFDI XML content.

        Args:
            cfdi_id: The CFDI ID (usually UUID)

        Returns:
            XML content as string
        """
        # Facturama returns XML encoded in base64
        response = await self._request(
            "GET",
            f"/api/Cfdi/Xml/{cfdi_id}",
        )

        if isinstance(response, dict) and "Content" in response:
            return base64.b64decode(response["Content"]).decode("utf-8")

        # If direct XML response
        return response if isinstance(response, str) else str(response)

    async def download_cfdi_pdf(self, cfdi_id: str) -> bytes:
        """
        Download CFDI PDF representation.

        Args:
            cfdi_id: The CFDI ID

        Returns:
            PDF content as bytes
        """
        response = await self._request(
            "GET",
            f"/api/Cfdi/Pdf/{cfdi_id}",
        )

        if isinstance(response, dict) and "Content" in response:
            return base64.b64decode(response["Content"])

        raise FacturamaError("Unexpected PDF response format")

    async def download_all_cfdis(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        include_received: bool = True,
        include_issued: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Download all CFDIs (both issued and received) with XML content.

        Args:
            start_date: Filter by start date
            end_date: Filter by end date
            include_received: Include received CFDIs
            include_issued: Include issued CFDIs

        Returns:
            List of dicts with metadata and XML content
        """
        results = []

        # Get issued CFDIs
        if include_issued:
            logger.info("Fetching issued CFDIs")
            issued = await self.list_cfdis_issued(start_date, end_date)
            for cfdi in issued:
                if not cfdi.cancelado:
                    try:
                        xml = await self.download_cfdi_xml(cfdi.uuid)
                        results.append({
                            "metadata": cfdi,
                            "xml": xml,
                            "type": "issued",
                        })
                    except FacturamaError as e:
                        logger.warning(
                            "Failed to download CFDI",
                            uuid=cfdi.uuid,
                            error=str(e),
                        )

        # Get received CFDIs
        if include_received:
            logger.info("Fetching received CFDIs")
            received = await self.list_cfdis_received(start_date, end_date)
            for cfdi in received:
                if not cfdi.cancelado:
                    try:
                        xml = await self.download_cfdi_xml(cfdi.uuid)
                        results.append({
                            "metadata": cfdi,
                            "xml": xml,
                            "type": "received",
                        })
                    except FacturamaError as e:
                        logger.warning(
                            "Failed to download CFDI",
                            uuid=cfdi.uuid,
                            error=str(e),
                        )

        logger.info(
            "CFDIs downloaded",
            total=len(results),
            issued=len([r for r in results if r["type"] == "issued"]),
            received=len([r for r in results if r["type"] == "received"]),
        )

        return results

    def _parse_cfdi_metadata(self, data: Dict[str, Any]) -> CFDIMetadata:
        """Parse CFDI metadata from API response."""
        # Handle date parsing
        fecha_emision = data.get("Date") or data.get("Fecha")
        if isinstance(fecha_emision, str):
            try:
                fecha_emision = datetime.fromisoformat(
                    fecha_emision.replace("Z", "+00:00")
                )
            except ValueError:
                fecha_emision = datetime.now()

        fecha_cancelacion = data.get("CancelationDate")
        if fecha_cancelacion and isinstance(fecha_cancelacion, str):
            try:
                fecha_cancelacion = datetime.fromisoformat(
                    fecha_cancelacion.replace("Z", "+00:00")
                )
            except ValueError:
                fecha_cancelacion = None

        return CFDIMetadata(
            uuid=data.get("Id") or data.get("Uuid", ""),
            folio=data.get("Folio"),
            serie=data.get("Serie"),
            fecha_emision=fecha_emision,
            tipo=data.get("CfdiType") or data.get("Tipo", "I"),
            total=float(data.get("Total", 0)),
            subtotal=float(data.get("Subtotal", 0)),
            descuento=float(data.get("Discount", 0) or data.get("Descuento", 0)),
            moneda=data.get("Currency") or data.get("Moneda", "MXN"),
            tipo_cambio=float(data.get("ExchangeRate", 1) or data.get("TipoCambio", 1)),
            metodo_pago=data.get("PaymentMethod") or data.get("MetodoPago"),
            forma_pago=data.get("PaymentForm") or data.get("FormaPago"),
            emisor_rfc=data.get("TaxEntityRfc") or data.get("EmisorRfc", ""),
            emisor_nombre=data.get("TaxEntityName") or data.get("EmisorNombre", ""),
            receptor_rfc=data.get("ReceiverRfc") or data.get("ReceptorRfc", ""),
            receptor_nombre=data.get("ReceiverName") or data.get("ReceptorNombre", ""),
            cancelado=data.get("Status") == "canceled" or data.get("Cancelado", False),
            fecha_cancelacion=fecha_cancelacion,
        )
