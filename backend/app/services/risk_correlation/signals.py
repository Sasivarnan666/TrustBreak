"""The normalized internal risk signal (Risk Engine 2.0). Stdlib only, no I/O.

Every analyzer output (message extraction, social-engineering indicators, behaviour anomalies, attachment
findings) is converted by `adapters.py` into this one shape, so the engine scores a single kind of object and a
future "same incident with signal X removed" run can feed a filtered list of signals through the same code.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskSignal:
    code: str
    category: str                       # IDENTITY | COMMUNICATION | FINANCIAL | BENEFICIARY | BEHAVIOUR | SOCIAL_ENGINEERING | ATTACHMENT
    source: str                         # rule | synthetic_baseline | AI | fallback | attachment_static | system  (WHERE the evidence came from)
    severity: str                       # derived from points
    points: int                         # points this signal contributes after confidence scaling, consolidation and caps
    title: str
    message: str                        # WHY it matters (explanation)
    details: list = field(default_factory=list)   # short items, e.g. executable file names
    why: Optional[str] = None           # WHY it matters (the rule's rationale; prototype reasoning, not a statistic)
    evidence: Optional[str] = None      # WHAT was observed (a quote, a comparison, a file name)
    confidence: Optional[str] = None    # low | medium | high where the evidence has one; None for deterministic comparisons
    group: Optional[str] = None         # consolidation group: one contribution per group
    analyzer: Optional[str] = None      # message | behaviour | attachment (which analyzer output it came from)
    base_points: Optional[int] = None   # points before a category cap (== points unless capped)
    capped: bool = False                # True when a category cap reduced `points`
    related_signal_codes: list = field(default_factory=list)   # signals merged into this one (same evidence)
    corroborating_sources: list = field(default_factory=list)  # other sources that reported the same evidence

    def to_dict(self) -> dict:
        return {
            "code": self.code, "category": self.category, "source": self.source, "severity": self.severity,
            "points": self.points, "title": self.title, "message": self.message, "details": list(self.details),
            "why": self.why, "evidence": self.evidence, "confidence": self.confidence, "group": self.group,
            "analyzer": self.analyzer, "base_points": self.base_points, "capped": self.capped,
            "related_signal_codes": list(self.related_signal_codes),
            "corroborating_sources": list(self.corroborating_sources),
        }
