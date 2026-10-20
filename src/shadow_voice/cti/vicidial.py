"""
VICIdial CTI Adapter
====================
Concrete dialer adapter for VICIdial:
- Non-Agent API (`/vicidial/non_agent_api.php`)
- Agent API (`/agc/api.php`)
- Dispositions: SALE, CALLBK, DNC, NI (Not Interested), XFER, AAM, DROP
- Blind and consultative Warm transfers
- Strict DNC write + read-back verification (HTTP 200 is not proof)
"""

from __future__ import annotations
import logging
import urllib.parse
from typing import Optional, Dict, Any, Set
import aiohttp
from shadow_voice.cti.base import BaseDialerAdapter, TransferResult, DispositionResult

logger = logging.getLogger("shadow_voice.vicidial")


class ViciDialAdapter(BaseDialerAdapter):
    """Production adapter for VICIdial CTI system."""

    def __init__(
        self,
        base_url: str = "http://vicidial.local",
        api_user: str = "shadow_api",
        api_pass: str = "shadow_secret",
        source: str = "shadow_voice_gateway",
        simulated: bool = False
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_user = api_user
        self.api_pass = api_pass
        self.source = source
        self.simulated = simulated

        # Simulated internal state for unit and integration testing
        self._mock_dnc_database: Set[str] = set()
        self._mock_dispositions: Dict[str, str] = {}

    def _build_url(self, endpoint: str, params: Dict[str, Any]) -> str:
        params["user"] = self.api_user
        params["pass"] = self.api_pass
        params["source"] = self.source
        query = urllib.parse.urlencode(params)
        return f"{self.base_url}/{endpoint.lstrip('/')}?{query}"

    async def transfer_blind(self, session_id: str, lead_id: str, extension: str) -> TransferResult:
        logger.info(f"[VICIdial] Blind transfer session={session_id} lead={lead_id} ext={extension}")
        if self.simulated:
            return TransferResult(
                success=True,
                session_id=session_id,
                target_extension=extension,
                transfer_type="BLIND",
                message="SUCCESS: Blind transfer executed"
            )

        url = self._build_url("agc/api.php", {
            "function": "transfer_conference",
            "value": "BLIND_TRANSFER",
            "phone_number": extension,
            "lead_id": lead_id
        })
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    text = await resp.text()
                    success = "SUCCESS" in text or "NOTICE" in text
                    return TransferResult(
                        success=success,
                        session_id=session_id,
                        target_extension=extension,
                        transfer_type="BLIND",
                        message=text.strip()
                    )
        except Exception as e:
            logger.error(f"[VICIdial] Blind transfer failed: {e}")
            return TransferResult(
                success=False,
                session_id=session_id,
                target_extension=extension,
                transfer_type="BLIND",
                message=f"Network error: {str(e)}"
            )

    async def transfer_warm(
        self,
        session_id: str,
        lead_id: str,
        extension: str,
        whisper_context: str
    ) -> TransferResult:
        logger.info(f"[VICIdial] Warm transfer session={session_id} lead={lead_id} ext={extension} context={whisper_context}")
        if self.simulated:
            return TransferResult(
                success=True,
                session_id=session_id,
                target_extension=extension,
                transfer_type="WARM",
                message="SUCCESS: Warm consultative transfer conference established"
            )

        sanitized_whisper = (whisper_context or "").replace("\r", " ").replace("\n", " ").strip()[:255]
        url = self._build_url("agc/api.php", {
            "function": "transfer_conference",
            "value": "WARM_TRANSFER",
            "phone_number": extension,
            "lead_id": lead_id,
            "notes": sanitized_whisper
        })
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    text = await resp.text()
                    success = "SUCCESS" in text or "NOTICE" in text
                    return TransferResult(
                        success=success,
                        session_id=session_id,
                        target_extension=extension,
                        transfer_type="WARM",
                        message=text.strip()
                    )
        except Exception as e:
            logger.error(f"[VICIdial] Warm transfer failed: {e}")
            return TransferResult(
                success=False,
                session_id=session_id,
                target_extension=extension,
                transfer_type="WARM",
                message=f"Network error: {str(e)}"
            )

    async def hangup_call(self, session_id: str, reason: str = "NORMAL_CLEARING") -> bool:
        logger.info(f"[VICIdial] Hangup session={session_id} ({reason})")
        if self.simulated:
            return True

        url = self._build_url("agc/api.php", {
            "function": "external_hangup",
            "value": "1"
        })
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
                    text = await resp.text()
                    return "SUCCESS" in text
        except Exception as e:
            logger.error(f"[VICIdial] Hangup request failed: {e}")
            return False

    async def set_disposition(
        self,
        session_id: str,
        lead_id: str,
        disposition_code: str,
        notes: str = ""
    ) -> DispositionResult:
        logger.info(f"[VICIdial] Setting dispo={disposition_code} lead={lead_id} notes='{notes}'")
        if self.simulated:
            self._mock_dispositions[lead_id] = disposition_code
            return DispositionResult(
                success=True,
                session_id=session_id,
                lead_id=lead_id,
                disposition_code=disposition_code,
                persisted=True,
                message="SUCCESS: Disposition persisted to lead record"
            )

        sanitized_notes = (notes or "").replace("\r", " ").replace("\n", " ").strip()[:255]
        url = self._build_url("agc/api.php", {
            "function": "external_status",
            "value": disposition_code,
            "lead_id": lead_id,
            "comments": sanitized_notes
        })
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
                    text = await resp.text()
                    success = "SUCCESS" in text
                    return DispositionResult(
                        success=success,
                        session_id=session_id,
                        lead_id=lead_id,
                        disposition_code=disposition_code,
                        persisted=success,
                        message=text.strip()
                    )
        except Exception as e:
            logger.error(f"[VICIdial] Set disposition failed: {e}")
            return DispositionResult(
                success=False,
                session_id=session_id,
                lead_id=lead_id,
                disposition_code=disposition_code,
                persisted=False,
                message=f"Network error: {str(e)}"
            )

    async def suppress_dnc(self, phone_number: str, campaign_id: str, reason: str) -> bool:
        clean_number = "".join(filter(str.isdigit, phone_number or ""))
        if not clean_number:
            logger.warning("[VICIdial DNC] Refusing to suppress empty/null phone number.")
            return False
        logger.warning(f"[VICIdial DNC] Adding {clean_number} to suppression list. Reason: {reason}")
        if self.simulated:
            self._mock_dnc_database.add(clean_number)
            return True

        url = self._build_url("vicidial/non_agent_api.php", {
            "function": "add_dnc",
            "phone_number": clean_number,
            "campaign_id": campaign_id
        })
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    text = await resp.text()
                    # Confirm response
                    if "SUCCESS" in text or "DNC ADDED" in text:
                        # Now execute read-back verification!
                        return await self.verify_dnc_suppression_state(clean_number)
                    return False
        except Exception as e:
            logger.error(f"[VICIdial] Suppress DNC request failed: {e}")
            return False

    async def verify_dnc_suppression_state(self, phone_number: str) -> bool:
        """
        Rule: HTTP 200 is not proof. Verify actual suppression state via supported VICIdial read-back mechanism.
        """
        clean_number = "".join(filter(str.isdigit, phone_number or ""))
        if not clean_number:
            return False
        if self.simulated:
            return clean_number in self._mock_dnc_database

        url = self._build_url("vicidial/non_agent_api.php", {
            "function": "check_dnc",
            "phone_number": clean_number
        })
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
                    text = await resp.text()
                    # Expect affirmative confirmation that number is in DNC list
                    is_present = "DNC_FOUND" in text or "PRESENT" in text or "RECORD_FOUND" in text
                    logger.info(f"[VICIdial DNC Readback] Number={clean_number} confirmed_suppressed={is_present}")
                    return is_present
        except Exception as e:
            logger.error(f"[VICIdial DNC Readback] Verification check failed: {e}")
            return False

    async def test_connection(self) -> Dict[str, Any]:
        """Tests VICIdial cluster API connectivity."""
        if self.simulated:
            return {
                "success": True,
                "simulated": True,
                "status": "online",
                "message": "VICIdial cluster simulator active. CTI API ready for calls.",
                "server": self.base_url
            }

        url = self._build_url("vicidial/non_agent_api.php", {"function": "version"})
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    text = await resp.text()
                    return {
                        "success": resp.status == 200,
                        "simulated": False,
                        "status": "online" if resp.status == 200 else "degraded",
                        "message": f"VICIdial response: {text[:100].strip()}",
                        "server": self.base_url
                    }
        except Exception as e:
            return {
                "success": False,
                "simulated": False,
                "status": "offline",
                "message": f"Connection error: {str(e)}",
                "server": self.base_url
            }

