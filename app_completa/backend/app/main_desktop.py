"""
FastAPI application for Desktop Financial Reconciliation System.
Reads from local folders instead of external APIs.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4
import json
import os

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
import structlog

from .config import get_settings
from .models import (
    ReconciliationJob,
    ReconciliationResult,
    ReconciliationStatus,
    Transaction,
)
from .local_scanner import LocalFolderScanner, validate_google_credentials
# Defer heavy imports to run_local_reconciliation
# from .ingestion import BankStatementParser, CFDIParser
# from .reconciliation import (
#     SafePeelingEngine,
#     LeidenClusterEngine,
#     LexicographicMILPSolver,
#     RescueLoopEngine,
# )
# from .utils.text_similarity import TextSimilarityEngine

logger = structlog.get_logger()
settings = get_settings()

# In-memory storage
jobs: dict[str, ReconciliationJob] = {}
results: dict[str, ReconciliationResult] = {}

# App base path (user's conciliacion folder)
APP_BASE_PATH = Path(os.environ.get(
    "CONCILIACION_BASE_PATH",
    os.environ.get("APP_BASE_PATH", Path.home() / "Documents" / "conciliacion")
))
# Credentials path - Check multiple locations
POSSIBLE_PATHS = [
    APP_BASE_PATH / "clave_API_cloud_vision.json",
    Path.home() / "Documents" / "proyecto_mama" / "clave_API_cloud_vision.json",
    Path("/Users/rodrigoperezcordero/Documents/proyecto_mama/clave_API_cloud_vision.json"),
]

CREDENTIALS_PATH = APP_BASE_PATH / "clave_API_cloud_vision.json"
for path in POSSIBLE_PATHS:
    if path.exists():
        CREDENTIALS_PATH = path
        logger.info(f"Found credentials at: {path}")
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
        break


def generate_debug_report():
    import os
    import sys
    import pulp
    import traceback
    from pathlib import Path
    from datetime import datetime
    
    # Try different write locations
    locations = [
        Path.home() / "Documents" / "conciliacion" / "DEBUG_RESULT.txt",
        Path.home() / "Documents" / "DEBUG_RESULT.txt",
        Path("/tmp/DEBUG_RESULT.txt")
    ]
    
    report = []
    try:
        report.append(f"Timestamp: {datetime.utcnow().isoformat()}")
    except:
        report.append("Timestamp: Error getting time")
        
    report.append(f"CWD: {os.getcwd()}")
    report.append(f"Frozen: {getattr(sys, 'frozen', False)}")
    report.append(f"MEIPASS: {getattr(sys, '_MEIPASS', 'Not Set')}")
    report.append(f"APP_BASE_PATH Env: {os.environ.get('CONCILIACION_BASE_PATH', 'Not Set')}")
    report.append(f"Python: {sys.version}")
    
    # Check License
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        lic_path_MEI = os.path.join(sys._MEIPASS, 'gurobi.lic')
        report.append(f"Checking _MEIPASS license: {lic_path_MEI} -> {os.path.exists(lic_path_MEI)}")
        if os.path.exists(lic_path_MEI):
             os.environ["GRB_LICENSE_FILE"] = lic_path_MEI
             report.append(f"Set GRB_LICENSE_FILE to {lic_path_MEI}")
    
    # Check Solver
    report.append(f"PuLP Version: {pulp.__version__}")
    try:
        prob = pulp.LpProblem("Test", pulp.LpMinimize)
        x = pulp.LpVariable("x", 0, 10, cat='Integer')
        prob += x >= 5
        # msg=1 to capture output if possible, though strict stdout is lost
        solver = pulp.GUROBI(msg=0, timeLimit=5)
        prob.solve(solver)
        report.append(f"Solver Status: {pulp.LpStatus[prob.status]}")
        report.append(f"Solver Value: {pulp.value(x)}")
    except Exception as e:
        report.append(f"Solver Error: {str(e)}")
        report.append(traceback.format_exc())

    content = "\n".join(report)
    
    for loc in locations:
        try:
            if not loc.parent.exists():
                try:
                    loc.parent.mkdir(parents=True, exist_ok=True)
                except:
                    pass
            with open(loc, "w") as f:
                f.write(content)
        except Exception as e:
             pass

generate_debug_report()



def setup_logging():
    """Configure logging to file and console."""
    import logging
    import sys
    
    log_dir = APP_BASE_PATH / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    
    # Configure standard logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    
    # Configure structlog to use standard logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Desktop Financial Reconciliation API")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    yield
    logger.info("Shutting down Desktop Financial Reconciliation API")


app = FastAPI(
    title="Conciliador Financiero",
    description="Sistema de conciliacion automatizada para macOS",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for Tauri
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://localhost:3000",
        "tauri://localhost",
        "http://tauri.localhost",
        "http://127.0.0.1:1420",
        "*", 
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ClientInfo(BaseModel):
    name: str
    file_count: int
    size_mb: float


class ScanResponse(BaseModel):
    pdf_clients: List[ClientInfo]
    cfdi_clients: List[ClientInfo]
    matched_clients: List[str]
    pdf_only_clients: List[str]
    cfdi_only_clients: List[str]
    warnings: List[str]
    errors: List[str]


class ValidationResponse(BaseModel):
    is_valid: bool
    message: str
    details: dict


class StartReconciliationRequest(BaseModel):
    pdf_client: str
    cfdi_client: str


class JobResponse(BaseModel):
    id: str
    status: str
    progress: float
    current_phase: str
    message: str


class SummaryResponse(BaseModel):
    total_invoices: int
    total_payments: int
    matched_invoices: int
    matched_payments: int
    unmatched_invoices: int
    unmatched_payments: int
    match_rate_invoices: float
    match_rate_payments: float
    processing_time_seconds: float


class SettingsUpdateRequest(BaseModel):
    max_abs_delta_cents: Optional[int] = None
    rel_delta_ratio: Optional[float] = None
    solver_timeout_seconds: Optional[int] = None
    max_cluster_size: Optional[int] = None
    # For future extensibility
    google_application_credentials: Optional[str] = None


class SettingsUpdateRequest(BaseModel):
    max_abs_delta_cents: Optional[int] = None
    rel_delta_ratio: Optional[float] = None
    solver_timeout_seconds: Optional[int] = None
    max_cluster_size: Optional[int] = None
    # For future extensibility
    google_application_credentials: Optional[str] = None



# API Endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/validate", response_model=ValidationResponse)
async def validate_setup():
    """Validate that all required files and folders exist."""
    scanner = LocalFolderScanner(base_path=APP_BASE_PATH)

    # Check folder structure
    folders_valid, folder_errors = scanner.validate_structure()

    # Check Google credentials
    creds_valid, creds_message = validate_google_credentials(str(CREDENTIALS_PATH))

    is_valid = folders_valid and creds_valid
    messages = []

    if not folders_valid:
        messages.extend(folder_errors)
    if not creds_valid:
        messages.append(creds_message)

    return ValidationResponse(
        is_valid=is_valid,
        message="\n\n".join(messages) if messages else "All validations passed",
        details={
            "folders_valid": folders_valid,
            "credentials_valid": creds_valid,
            "pdf_folder": str(scanner.pdf_folder),
            "cfdi_folder": str(scanner.cfdi_folder),
            "credentials_path": str(CREDENTIALS_PATH),
        }
    )


@app.get("/api/scan", response_model=ScanResponse)
async def scan_folders():
    """Scan PDF and CFDI folders for client subfolders."""
    scanner = LocalFolderScanner(base_path=APP_BASE_PATH)
    result = scanner.scan_all()

    return ScanResponse(
        pdf_clients=[
            ClientInfo(name=c.name, file_count=c.file_count, size_mb=round(c.size_mb, 2))
            for c in result.pdf_clients
        ],
        cfdi_clients=[
            ClientInfo(name=c.name, file_count=c.file_count, size_mb=round(c.size_mb, 2))
            for c in result.cfdi_clients
        ],
        matched_clients=result.matched_clients,
        pdf_only_clients=result.pdf_only_clients,
        cfdi_only_clients=result.cfdi_only_clients,
        warnings=result.warnings,
        errors=result.errors,
    )


@app.post("/api/reconciliation/start", response_model=JobResponse)
async def start_reconciliation(
    request: StartReconciliationRequest,
    background_tasks: BackgroundTasks,
):
    """Start a new reconciliation job."""
    job_id = str(uuid4())

    # Validate clients exist
    scanner = LocalFolderScanner(base_path=APP_BASE_PATH)
    pdf_files = scanner.get_pdf_files(request.pdf_client)
    cfdi_files = scanner.get_cfdi_files(request.cfdi_client)

    if not pdf_files:
        raise HTTPException(400, f"No PDF files found for client: {request.pdf_client}")
    if not cfdi_files:
        raise HTTPException(400, f"No CFDI files found for client: {request.cfdi_client}")

    # Validate Credentials explicitly
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", str(CREDENTIALS_PATH))
    is_valid, msg = validate_google_credentials(creds_path)
    if not is_valid:
         raise HTTPException(400, f"Error de credenciales (Google Cloud Vision): {msg}")

    # Create job
    job = ReconciliationJob(
        id=job_id,
        bank_files=[str(f) for f in pdf_files],
        rfc=request.cfdi_client,  # Using client name as identifier
        status=ReconciliationStatus.PENDING,
    )
    jobs[job_id] = job

    # Start background processing
    background_tasks.add_task(
        run_local_reconciliation,
        job,
        pdf_files,
        cfdi_files,
    )

    logger.info(
        "Reconciliation job started",
        job_id=job_id,
        pdf_client=request.pdf_client,
        cfdi_client=request.cfdi_client,
    )

    return JobResponse(
        id=job.id,
        status=job.status.value,
        progress=0,
        current_phase="Iniciando...",
        message=f"Procesando {len(pdf_files)} PDFs y {len(cfdi_files)} CFDIs",
    )


async def run_local_reconciliation(
    job: ReconciliationJob,
    pdf_files: List[Path],
    cfdi_files: List[Path],
):
    """Background task to run reconciliation on local files."""
    import time
    
    # Deferred imports to speed up startup
    from .ingestion import BankStatementParser, CFDIParser
    from .reconciliation import (
        SafePeelingEngine,
        LeidenClusterEngine,
        LexicographicMILPSolver,
        RescueLoopEngine,
    )
    from .utils.text_similarity import TextSimilarityEngine

    start_time = time.time()

    result = ReconciliationResult(job_id=job.id)
    bank_parser = BankStatementParser()
    cfdi_parser = CFDIParser()
    similarity_engine = TextSimilarityEngine()
    peeling_engine = SafePeelingEngine()
    cluster_engine = LeidenClusterEngine()
    solver = LexicographicMILPSolver()
    rescue_engine = RescueLoopEngine()

    try:
        job.status = ReconciliationStatus.PROCESSING
        job.started_at = datetime.utcnow()

        # Phase 1: Ingest PDFs
        job.current_phase = "Procesando estados de cuenta..."
        job.progress = 5

        bank_transactions = []
        for i, pdf_path in enumerate(pdf_files):
            job.current_phase = f"Procesando PDF {i+1}/{len(pdf_files)}: {pdf_path.name}"
            job.progress = 5 + (20 * (i + 1) / len(pdf_files))

            try:
                parse_result = await bank_parser.parse_pdf(str(pdf_path))
                bank_transactions.extend(parse_result.transactions)
            except Exception as e:
                logger.error(f"Error parsing PDF: {pdf_path}", error=str(e))
                result.warnings.append(f"Error en {pdf_path.name}: {str(e)}")

        # Phase 2: Parse CFDIs
        job.current_phase = "Procesando facturas CFDI..."
        job.progress = 30

        cfdi_transactions = []
        for i, cfdi_path in enumerate(cfdi_files):
            job.progress = 30 + (15 * (i + 1) / len(cfdi_files))

            try:
                with open(cfdi_path, "r", encoding="utf-8") as f:
                    xml_content = f.read()
                parse_result = cfdi_parser.parse_xml(xml_content, str(cfdi_path))
                if parse_result.transaction:
                    cfdi_transactions.append(parse_result.transaction)
            except Exception as e:
                logger.error(f"Error parsing CFDI: {cfdi_path}", error=str(e))
                result.warnings.append(f"Error en {cfdi_path.name}: {str(e)}")

        # Phase 3: Compute embeddings
        job.current_phase = "Calculando similitud de textos..."
        job.progress = 50

        all_transactions = bank_transactions + cfdi_transactions
        texts = [
            " ".join(filter(None, [t.counterparty_name, t.description, t.reference]))
            for t in all_transactions
        ]
        embeddings = await similarity_engine.encode_batch(texts)
        for txn, emb in zip(all_transactions, embeddings):
            txn.embedding = emb

        # Separate invoices and payments
        from .models import TransactionSource
        invoices = [t for t in all_transactions if t.source == TransactionSource.CFDI]
        payments = [t for t in all_transactions if t.source == TransactionSource.BANK]

        # Phase 4: Safe Peeling
        job.current_phase = "Safe Peeling (Fase 0)..."
        job.status = ReconciliationStatus.PEELING
        job.progress = 55

        from datetime import date
        peeling_result = await asyncio.to_thread(peeling_engine.process, invoices, payments, date.today())
        result.matched_pairs.extend(peeling_result.matched_pairs)
        result.audit_log.extend(peeling_result.audit_entries)

        remaining_invoices = peeling_result.remaining_invoices
        remaining_payments = peeling_result.remaining_payments

        # Phase 5: Clustering
        job.current_phase = "Clustering Leiden (Fase 1)..."
        job.status = ReconciliationStatus.CLUSTERING
        job.progress = 65

        clustering_result = await asyncio.to_thread(cluster_engine.process, remaining_invoices, remaining_payments)
        result.audit_log.extend(clustering_result.audit_entries)

        # Phase 6: MILP Solving
        job.current_phase = "Resolviendo MILP (Fase 2)..."
        job.status = ReconciliationStatus.SOLVING
        job.progress = 70

        solver_results = []
        failed_results = []
        total_clusters = len(clustering_result.clusters)

        for i, cluster in enumerate(clustering_result.clusters):
            job.current_phase = f"Resolviendo cluster {i+1}/{total_clusters}"
            job.progress = 70 + (20 * (i + 1) / max(total_clusters, 1))

            headers = {"Content-Type": "application/json"} # Redundant? No, loop logic
            solver_result = await asyncio.to_thread(solver.solve_cluster, cluster)
            result.audit_log.extend(solver_result.audit_entries)

            if solver_result.needs_rescue:
                failed_results.append(solver_result)
            else:
                solver_results.append(solver_result)
                result.matched_pairs.extend(solver_result.matched_pairs)
                result.partial_matches.extend(solver_result.partial_matches)

        # Phase 7: Rescue Loop
        if failed_results:
            job.current_phase = f"Rescue Loop (Fase 3): {len(failed_results)} clusters"
            job.status = ReconciliationStatus.RESCUE
            job.progress = 92

            rescue_result = await asyncio.to_thread(
                rescue_engine.process,
                failed_results,
                clustering_result.clusters,
                clustering_result.orphan_invoices,
                clustering_result.orphan_payments,
            )

            result.audit_log.extend(rescue_result.audit_entries)
            result.manual_review.extend(rescue_result.manual_review)

            for sr in rescue_result.solver_results:
                result.matched_pairs.extend(sr.matched_pairs)
                result.partial_matches.extend(sr.partial_matches)

        # Collect unmatched
        matched_invoice_ids = set()
        matched_payment_ids = set()

        for pair in result.matched_pairs:
            matched_invoice_ids.update(pair.invoice_ids)
            matched_payment_ids.update(pair.payment_ids)

        for partial in result.partial_matches:
            matched_invoice_ids.add(partial.invoice_id)
            matched_payment_ids.update(partial.payment_ids)

        result.unmatched_invoices = [
            inv.id for inv in invoices if inv.id not in matched_invoice_ids
        ]
        result.unmatched_payments = [
            pay.id for pay in payments if pay.id not in matched_payment_ids
        ]

        # Compute summary
        job.current_phase = "Generando reporte..."
        job.progress = 98

        from .models import ReconciliationSummary
        result.summary = ReconciliationSummary(
            total_invoices=len(invoices),
            total_payments=len(payments),
            matched_invoices=len(matched_invoice_ids),
            matched_payments=len(matched_payment_ids),
            unmatched_invoices=len(result.unmatched_invoices),
            unmatched_payments=len(result.unmatched_payments),
            manual_review_count=len(result.manual_review),
            total_invoice_amount_cents=sum(inv.amount_cents for inv in invoices),
            total_payment_amount_cents=sum(pay.amount_cents for pay in payments),
            matched_amount_cents=sum(p.total_invoice_cents for p in result.matched_pairs),
            processing_time_seconds=time.time() - start_time,
        )

        # Complete
        job.status = ReconciliationStatus.COMPLETED
        job.progress = 100
        job.current_phase = "Completado"
        job.completed_at = datetime.utcnow()
        result.status = ReconciliationStatus.COMPLETED
        result.completed_at = datetime.utcnow()

        results[job.id] = result

        logger.info(
            "Reconciliation complete",
            job_id=job.id,
            matched=len(result.matched_pairs) + len(result.partial_matches),
            time=result.summary.processing_time_seconds,
        )

    except Exception as e:
        logger.exception("Reconciliation failed", job_id=job.id)
        job.status = ReconciliationStatus.FAILED
        job.current_phase = f"Error: {str(e)}"
        result.status = ReconciliationStatus.FAILED
        result.errors.append(str(e))
        results[job.id] = result


@app.get("/api/reconciliation/{job_id}/status", response_model=JobResponse)
async def get_job_status(job_id: str):
    """Get status of a reconciliation job."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    job = jobs[job_id]
    return JobResponse(
        id=job.id,
        status=job.status.value,
        progress=job.progress,
        current_phase=job.current_phase,
        message="",
    )


@app.get("/api/reconciliation/{job_id}/result")
async def get_job_result(job_id: str):
    """Get result of a completed reconciliation job."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    job = jobs[job_id]
    if job.status not in (ReconciliationStatus.COMPLETED, ReconciliationStatus.FAILED):
        raise HTTPException(400, f"Job not finished. Status: {job.status.value}")

    if job_id not in results:
        raise HTTPException(404, "Result not found")

    result = results[job_id]

    return {
        "job_id": result.job_id,
        "status": result.status.value,
        "matched_pairs": [
            {
                "id": pair.id,
                "invoice_ids": pair.invoice_ids,
                "payment_ids": pair.payment_ids,
                "total_invoice": pair.total_invoice_cents / 100,
                "total_payment": pair.total_payment_cents / 100,
                "gap": pair.gap_cents / 100,
                "confidence": pair.confidence.value,
                "commit_status": pair.commit_status.value,
            }
            for pair in result.matched_pairs
        ],
        "partial_matches": [
            {
                "id": partial.id,
                "invoice_id": partial.invoice_id,
                "invoice_amount": partial.invoice_amount_cents / 100,
                "paid_amount": partial.paid_amount_cents / 100,
                "remainder": partial.remainder_cents / 100,
                "percentage_paid": partial.percentage_paid,
            }
            for partial in result.partial_matches
        ],
        "unmatched_invoices": len(result.unmatched_invoices),
        "unmatched_payments": len(result.unmatched_payments),
        "manual_review_count": len(result.manual_review),
        "summary": {
            "total_invoices": result.summary.total_invoices,
            "total_payments": result.summary.total_payments,
            "matched_invoices": result.summary.matched_invoices,
            "matched_payments": result.summary.matched_payments,
            "match_rate_invoices": result.summary.match_rate_invoices,
            "match_rate_payments": result.summary.match_rate_payments,
            "processing_time": round(result.summary.processing_time_seconds, 2),
        },
        "errors": result.errors,
        "warnings": result.warnings,
    }


@app.get("/api/reconciliation/{job_id}/export")
async def export_result(job_id: str):
    """Export reconciliation result to JSON file."""
    if job_id not in results:
        raise HTTPException(404, "Result not found")

    result = results[job_id]
    output_path = settings.reports_dir / f"conciliacion_{job_id}.json"

    data = {
        "job_id": result.job_id,
        "fecha_exportacion": datetime.utcnow().isoformat(),
        "resumen": {
            "total_facturas": result.summary.total_invoices,
            "total_pagos": result.summary.total_payments,
            "facturas_conciliadas": result.summary.matched_invoices,
            "pagos_conciliados": result.summary.matched_payments,
            "tasa_conciliacion_facturas": f"{result.summary.match_rate_invoices:.1f}%",
            "tasa_conciliacion_pagos": f"{result.summary.match_rate_payments:.1f}%",
            "tiempo_procesamiento": f"{result.summary.processing_time_seconds:.2f}s",
        },
        "pares_conciliados": [
            {
                "facturas": pair.invoice_ids,
                "pagos": pair.payment_ids,
                "monto_factura": pair.total_invoice_cents / 100,
                "monto_pago": pair.total_payment_cents / 100,
                "diferencia": pair.gap_cents / 100,
                "confianza": pair.confidence.value,
            }
            for pair in result.matched_pairs
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return FileResponse(
        output_path,
        media_type="application/json",
        filename=f"conciliacion_{job_id}.json",
    )


from .utils.config_utils import update_env_file

@app.get("/settings", response_model=SettingsUpdateRequest)
async def get_settings_endpoint():
    """Get current application settings."""
    s = get_settings()
    return SettingsUpdateRequest(
        max_abs_delta_cents=s.max_abs_delta_cents,
        rel_delta_ratio=s.rel_delta_ratio,
        solver_timeout_seconds=s.solver_timeout_seconds,
        max_cluster_size=s.max_cluster_size,
        google_application_credentials=s.google_application_credentials
    )

@app.post("/settings")
async def update_settings(request: SettingsUpdateRequest):
    """Update application settings in .env file."""
    try:
        updates = {}
        if request.max_abs_delta_cents is not None:
            updates["MAX_ABS_DELTA_CENTS"] = request.max_abs_delta_cents
        if request.rel_delta_ratio is not None:
            updates["REL_DELTA_RATIO"] = request.rel_delta_ratio
        if request.solver_timeout_seconds is not None:
            updates["SOLVER_TIMEOUT_SECONDS"] = request.solver_timeout_seconds
        if request.max_cluster_size is not None:
            updates["MAX_CLUSTER_SIZE"] = request.max_cluster_size
        if request.google_application_credentials is not None:
            updates["GOOGLE_APPLICATION_CREDENTIALS"] = request.google_application_credentials
            
        success = update_env_file(updates)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to write to .env file")
            
        return {"status": "success", "message": "Settings updated. Restart required."}
        
    except Exception as e:
        logger.error("Failed to update settings", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
