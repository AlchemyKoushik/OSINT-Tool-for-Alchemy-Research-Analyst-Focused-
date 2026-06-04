from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


@dataclass
class AgentContext:
    topic: str
    section: str
    session_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResearchPlannerAgent(Protocol):
    def plan(self, context: AgentContext) -> Dict[str, Any]:
        ...


class EvidenceAgent(Protocol):
    def gather(self, context: AgentContext) -> List[Dict[str, Any]]:
        ...


class VerificationAgent(Protocol):
    def verify(self, context: AgentContext, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        ...


class ReportAgent(Protocol):
    def compose(self, context: AgentContext, verified_payload: Dict[str, Any]) -> Dict[str, Any]:
        ...
