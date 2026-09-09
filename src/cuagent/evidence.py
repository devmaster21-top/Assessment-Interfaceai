from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact


class EvidenceLogger:
    def __init__(self, root: Path, run_id: str, run_type: str):
        self.root = root
        self.run_id = run_id
        self.run_type = run_type
        self.log_dir = root / "logs"
        self.screenshot_dir = root / "screenshots" / run_id
        self.intervention_dir = root / "interventions"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.intervention_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{run_type}-{run_id}.jsonl"

    def emit(self, event: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "run_type": self.run_type,
            "event": event,
            **redact(payload),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
