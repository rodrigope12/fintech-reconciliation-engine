"""
Audit logging for reconciliation decisions.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import structlog

from ..config import get_settings
from ..models import AuditEntry

logger = structlog.get_logger()


class AuditLogger:
    """
    Logger for audit trail of reconciliation decisions.
    Provides both in-memory and file-based logging.
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.entries: List[AuditEntry] = []
        self.settings = get_settings()

    def log(self, entry: AuditEntry) -> None:
        """Add an audit entry."""
        self.entries.append(entry)

        # Also log to structlog
        logger.info(
            entry.message,
            action=entry.action.value,
            transaction_ids=entry.transaction_ids,
            cluster_id=entry.cluster_id,
            success=entry.success,
        )

    def log_many(self, entries: List[AuditEntry]) -> None:
        """Add multiple audit entries."""
        for entry in entries:
            self.log(entry)

    def get_entries(
        self,
        action_filter: Optional[str] = None,
        success_only: bool = False,
    ) -> List[AuditEntry]:
        """Get filtered audit entries."""
        entries = self.entries

        if action_filter:
            entries = [e for e in entries if e.action.value == action_filter]

        if success_only:
            entries = [e for e in entries if e.success]

        return entries

    def export_to_file(self, output_path: Optional[Path] = None) -> Path:
        """Export audit log to JSON file."""
        if output_path is None:
            output_path = self.settings.reports_dir / f"audit_{self.job_id}.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "job_id": self.job_id,
            "exported_at": datetime.utcnow().isoformat(),
            "total_entries": len(self.entries),
            "entries": [
                {
                    "id": e.id,
                    "timestamp": e.timestamp.isoformat(),
                    "action": e.action.value,
                    "transaction_ids": e.transaction_ids,
                    "cluster_id": e.cluster_id,
                    "solver_phase": e.solver_phase.value if e.solver_phase else None,
                    "message": e.message,
                    "details": e.details,
                    "success": e.success,
                    "error_message": e.error_message,
                }
                for e in self.entries
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Audit log exported", path=str(output_path))
        return output_path

    def summary(self) -> dict:
        """Get summary statistics of audit log."""
        from collections import Counter

        action_counts = Counter(e.action.value for e in self.entries)
        success_count = sum(1 for e in self.entries if e.success)
        error_count = sum(1 for e in self.entries if not e.success)

        return {
            "total_entries": len(self.entries),
            "success_count": success_count,
            "error_count": error_count,
            "action_counts": dict(action_counts),
        }
