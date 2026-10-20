"""
Dialer Adapter Factory
======================
Decouples conversational engine from concrete CTI implementations.
Supports runtime dialer registration and instantiation.
"""

from __future__ import annotations
from typing import Dict, Type, Any
from shadow_voice.cti.base import BaseDialerAdapter
from shadow_voice.cti.vicidial import ViciDialAdapter


class DialerFactory:
    """Factory creating dialer adapter instances."""
    _registry: Dict[str, Type[BaseDialerAdapter]] = {
        "vicidial": ViciDialAdapter
    }

    @classmethod
    def register(cls, name: str, adapter_cls: Type[BaseDialerAdapter]) -> None:
        cls._registry[name.lower()] = adapter_cls

    @classmethod
    def create(cls, name: str = "vicidial", **kwargs: Any) -> BaseDialerAdapter:
        key = (name or "vicidial").strip().lower()
        adapter_cls = cls._registry.get(key)
        if not adapter_cls:
            raise ValueError(f"Unknown dialer type '{name}'. Registered: {list(cls._registry.keys())}")
        return adapter_cls(**kwargs)
