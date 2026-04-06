from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RealtimeIntent:
    domain: str
    raw_text: str
    entities: Dict[str, Any] = field(default_factory=dict)
    time_scope: str = "now"
    confidence: float = 0.0


@dataclass
class RealtimeResult:
    ok: bool
    domain: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "internal"
    updated_at: str = ""
    cache_hit: bool = False
    status: str = "success"
    should_ask_followup: bool = False
    followup_question: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "domain": self.domain,
            "message": self.message,
            "data": self.data,
            "source": self.source,
            "updated_at": self.updated_at,
            "cache_hit": self.cache_hit,
            "status": self.status,
            "should_ask_followup": self.should_ask_followup,
            "followup_question": self.followup_question,
        }


@dataclass
class RealtimeProviderPayload:
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    updated_at: str = ""
    message: str = ""
