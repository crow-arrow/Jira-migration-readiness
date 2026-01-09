from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    PASS = "PASS"
    INFO = "INFO"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCKER = "BLOCKER"


class CheckResult(BaseModel):
    id: str
    title: str
    severity: Severity
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    affected: List[str] = Field(default_factory=list)
    remediation: Optional[str] = None


class Summary(BaseModel):
    pass_count: int = 0
    info_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    blocker_count: int = 0


class Report(BaseModel):
    tool: str = "jmrt"
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    target: str
    summary: Summary
    checks: List[CheckResult]
