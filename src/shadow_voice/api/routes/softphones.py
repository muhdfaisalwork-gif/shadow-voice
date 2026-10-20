"""
Softphones API Router
=====================
Endpoints for managing Eyebeam, X-Lite, and Built-in Virtual SIP Softphones:
- Detection of workspace installers (Eyebeam.exe, x-lite-eyebeam.exe)
- Process launching, monitoring, and stopping
- Windows Registry (.reg) auto-provisioning with Auto-Answer
- Headless Virtual SIP softphone registration to VICIdial / Asterisk
- Step-by-step dialer softphone setup guides
"""

from __future__ import annotations
import os
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from shadow_voice.core.db import get_connection
from shadow_voice.telephony.softphone_manager import (
    SoftphoneDetector,
    SoftphoneProcessController,
    EyebeamRegistryProvisioner,
    virtual_softphone
)

logger = logging.getLogger("shadow_voice.api.softphones")
router = APIRouter(prefix="/api/softphones", tags=["Softphones & Workstations"])


class LaunchRequest(BaseModel):
    softphone_type: str = "eyebeam"  # "eyebeam" or "xlite"
    mode: str = "interactive"        # "interactive" or "silent"


class StopRequest(BaseModel):
    softphone_type: str = "eyebeam"


class UpdateSoftphoneRequest(BaseModel):
    name: Optional[str] = None
    extension: str = "1001"
    secret: Optional[str] = None
    server_ip: str = "192.168.1.100"
    sip_port: int = 5060
    auto_answer: bool = True
    notes: Optional[str] = ""


class GenerateRegRequest(BaseModel):
    extension: str = "1001"
    password: str = "test1001"
    server_ip: str = "192.168.1.100"
    sip_port: int = 5060
    auto_answer: bool = True
    display_name: Optional[str] = None


class VirtualSIPRegisterRequest(BaseModel):
    extension: str = "8388"
    password: str = "test8388"
    server_ip: str = "192.168.1.100"
    sip_port: int = 5060


@router.get("/status")
def get_softphone_status() -> Dict[str, Any]:
    """Returns executable detection, process runtime status, and configurations."""
    installers = SoftphoneDetector.get_workspace_installers()
    installed = SoftphoneDetector.get_installed_binaries()
    processes = SoftphoneProcessController.get_running_processes()
    virt_status = virtual_softphone.get_status()

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM softphone_configs ORDER BY id ASC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    configs = {}
    for r in rows:
        if r.get("secret"):
            r["secret"] = "********"
        configs[r["id"]] = r

    return {
        "installers": installers,
        "installed": installed,
        "processes": processes,
        "virtual_sip": virt_status,
        "configs": configs
    }


@router.put("/{softphone_id}")
def update_softphone_config(softphone_id: str, req: UpdateSoftphoneRequest) -> Dict[str, Any]:
    """Updates configuration for a softphone profile (extension, IP, auto-answer)."""
    clean_ext = (req.extension or "").strip()
    if not clean_ext:
        raise HTTPException(status_code=400, detail="Extension cannot be empty.")
    clean_ip = (req.server_ip or "").strip()
    if not clean_ip:
        raise HTTPException(status_code=400, detail="Server IP cannot be empty.")
    if not (1 <= req.sip_port <= 65535):
        raise HTTPException(status_code=400, detail="Invalid SIP port (must be 1-65535).")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT secret FROM softphone_configs WHERE id = ?", (softphone_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Softphone config not found")

    secret = req.secret
    if secret in ("********", "••••••••") or not secret:
        secret = row["secret"]

    c.execute("""
        UPDATE softphone_configs
        SET extension = ?, secret = ?, server_ip = ?, sip_port = ?,
            auto_answer = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        clean_ext, secret, clean_ip, req.sip_port,
        1 if req.auto_answer else 0, req.notes, softphone_id
    ))
    conn.commit()
    conn.close()

    return {"success": True, "message": f"{softphone_id} configuration updated."}


@router.post("/launch")
def launch_softphone(req: LaunchRequest) -> Dict[str, Any]:
    """Launches Eyebeam or X-Lite (supports interactive GUI or silent background install)."""
    res = SoftphoneProcessController.launch(softphone_type=req.softphone_type, mode=req.mode)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.post("/stop")
def stop_softphone(req: StopRequest) -> Dict[str, Any]:
    """Terminates active softphone process."""
    return SoftphoneProcessController.stop(softphone_type=req.softphone_type)


@router.post("/generate-reg")
def generate_registry_file(req: GenerateRegRequest) -> Dict[str, Any]:
    """Generates CounterPath eyeBeam Windows Registry (.reg) content."""
    reg_text = EyebeamRegistryProvisioner.generate_reg_content(
        extension=req.extension,
        password=req.password,
        server_ip=req.server_ip,
        sip_port=req.sip_port,
        display_name=req.display_name or req.extension,
        auto_answer=req.auto_answer
    )
    return {
        "success": True,
        "extension": req.extension,
        "server_ip": req.server_ip,
        "reg_content": reg_text
    }


@router.get("/download-reg")
def download_registry_file(
    extension: str = "1001",
    password: str = "test1001",
    server_ip: str = "192.168.1.100",
    sip_port: int = 5060,
    auto_answer: bool = True
) -> Response:
    """Streams a downloadable .reg file for 1-click Windows registry import."""
    reg_text = EyebeamRegistryProvisioner.generate_reg_content(
        extension=extension,
        password=password,
        server_ip=server_ip,
        sip_port=sip_port,
        auto_answer=auto_answer
    )
    filename = f"eyebeam_vicidial_{extension}.reg"
    return Response(
        content=reg_text,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.post("/apply-reg")
def apply_registry_file(req: GenerateRegRequest) -> Dict[str, Any]:
    """Directly applies the generated eyeBeam profile to the Windows Registry on this host."""
    res = EyebeamRegistryProvisioner.apply_to_windows_registry(
        extension=req.extension,
        password=req.password,
        server_ip=req.server_ip,
        sip_port=req.sip_port,
        auto_answer=req.auto_answer
    )
    return res


@router.post("/virtual/register")
async def register_virtual_softphone(req: VirtualSIPRegisterRequest) -> Dict[str, Any]:
    """Connects the built-in Virtual SIP softphone to VICIdial/Asterisk."""
    clean_ext = (req.extension or "").strip()
    clean_ip = (req.server_ip or "").strip()
    if not clean_ext:
        raise HTTPException(status_code=400, detail="Extension cannot be empty.")
    if not clean_ip:
        raise HTTPException(status_code=400, detail="Server IP cannot be empty.")
    if not (1 <= req.sip_port <= 65535):
        raise HTTPException(status_code=400, detail="Invalid SIP port (must be 1-65535).")

    virtual_softphone.extension = clean_ext
    virtual_softphone.password = (req.password or "").strip()
    virtual_softphone.server_ip = clean_ip
    virtual_softphone.sip_port = req.sip_port
    res = await virtual_softphone.start()
    return res


@router.post("/virtual/unregister")
async def unregister_virtual_softphone() -> Dict[str, Any]:
    """Disconnects the built-in Virtual SIP softphone."""
    res = await virtual_softphone.stop()
    return res


@router.get("/guide")
def get_softphone_guide() -> Dict[str, Any]:
    """Returns step-by-step instructions for connecting Eyebeam / X-Lite to VICIdial."""
    return {
        "title": "Eyebeam & X-Lite VICIdial Connection Guide",
        "overview": (
            "In VICIdial, agents use Eyebeam or X-Lite to log in. "
            "When the agent logs into the VICIdial agent screen (agc/vicidial.php), "
            "VICIdial calls the softphone extension. The softphone auto-answers into "
            "the MeetMe conference room, and VICIdial pumps live connected customer calls "
            "into that conference."
        ),
        "steps": [
            {
                "step": 1,
                "title": "Configure Phone Extension in VICIdial Admin",
                "instructions": (
                    "In VICIdial Admin -> Admin -> Phones -> Add Phone:\n"
                    "• Extension: 1001\n"
                    "• Dialplan Number: 1001\n"
                    "• Server IP: <Your VICIdial Server IP>\n"
                    "• Protocol: SIP\n"
                    "• Login: 1001\n"
                    "• Pass: test1001\n"
                    "• Status: ACTIVE"
                )
            },
            {
                "step": 2,
                "title": "Configure Eyebeam SIP Account (or Apply 1-Click .reg)",
                "instructions": (
                    "In Eyebeam: Right-click -> SIP Account Settings -> Add:\n"
                    "• Display Name: 1001\n"
                    "• User Name: 1001\n"
                    "• Password: test1001\n"
                    "• Authorization User Name: 1001\n"
                    "• Domain: <Your VICIdial Server IP>\n"
                    "• Register with domain: Checked\n"
                    "• Or simply click 'Apply to Registry' in Shadow Voice Studio to pre-configure automatically!"
                )
            },
            {
                "step": 3,
                "title": "Enable Auto-Answer in Eyebeam (Critical)",
                "instructions": (
                    "In Eyebeam: Right-click -> Options -> Calls -> Check 'Auto Answer after 0 seconds'.\n"
                    "This ensures Eyebeam picks up the VICIdial MeetMe call immediately without ringing."
                )
            },
            {
                "step": 4,
                "title": "Log Into VICIdial Agent Screen",
                "instructions": (
                    "Open http://<VICIDIAL_IP>/agc/vicidial.php in your browser:\n"
                    "• Phone Login: 1001\n"
                    "• Phone Password: test1001\n"
                    "• User Login: 6666\n"
                    "• User Password: <Your User Pass>\n"
                    "• Campaign: <Your Outbound Campaign>\n"
                    "Click Submit -> Eyebeam will auto-answer and connect to the conference!"
                )
            },
            {
                "step": 5,
                "title": "Optional: Use Built-in Virtual SIP Softphone (Headless)",
                "instructions": (
                    "If you don't want desktop softphone windows open, click 'Connect Virtual SIP Agent' "
                    "in Shadow Voice Studio. Shadow Voice will register to VICIdial as an agent extension, "
                    "auto-answer the MeetMe call, and stream audio directly to the AI engine!"
                )
            }
        ]
    }
