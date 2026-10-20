from shadow_voice.cti.base import BaseDialerAdapter, TransferResult, DispositionResult
from shadow_voice.cti.vicidial import ViciDialAdapter
from shadow_voice.cti.factory import DialerFactory
from shadow_voice.cti.lead_history import LeadHistoryStore, LeadHistoryRecord, CallHistoryEntry

__all__ = [
    "BaseDialerAdapter",
    "TransferResult",
    "DispositionResult",
    "ViciDialAdapter",
    "DialerFactory",
    "LeadHistoryStore",
    "LeadHistoryRecord",
    "CallHistoryEntry",
]
