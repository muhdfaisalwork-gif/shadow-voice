"""
Softphone & SIP Workstation Verification Suite
==============================================
Validates:
1. Workspace installer detection (Eyebeam.exe, x-lite-eyebeam.exe)
2. Softphone process tracking and controllers
3. CounterPath eyeBeam Windows Registry (.reg) auto-provisioning with Auto-Answer
4. Headless Virtual SIP Softphone protocol packets (REGISTER, 200 OK SDP, state machine)
5. FastAPI softphone endpoints (/api/softphones/*)
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient

from shadow_voice.core.db import init_db, get_connection
from shadow_voice.telephony.softphone_manager import (
    SoftphoneDetector,
    SoftphoneProcessController,
    EyebeamRegistryProvisioner,
    VirtualSIPSoftphone,
    virtual_softphone
)
from shadow_voice.api.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_softphone_detector_discovers_workspace_installers():
    """Verify Eyebeam.exe and x-lite-eyebeam.exe in workspace root are detected."""
    installers = SoftphoneDetector.get_workspace_installers()

    assert "eyebeam" in installers
    assert "xlite" in installers

    # Eyebeam.exe should be present in root
    eb = installers["eyebeam"]
    assert eb["available"] is True
    assert eb["size_mb"] >= 2.0
    assert os.path.exists(eb["path"])
    assert eb["is_installer"] is True

    # x-lite-eyebeam.exe should be present in root
    xl = installers["xlite"]
    assert xl["available"] is True
    assert xl["size_mb"] >= 5.0
    assert os.path.exists(xl["path"])
    assert xl["is_installer"] is True


def test_softphone_detector_installed_binaries():
    """Verify checking for installed CounterPath binaries returns clean structure."""
    installed = SoftphoneDetector.get_installed_binaries()
    assert "eyebeam" in installed
    assert "xlite" in installed
    assert isinstance(installed["eyebeam"]["installed"], bool)
    assert isinstance(installed["xlite"]["installed"], bool)


def test_softphone_process_controller_query():
    """Verify running softphone process inspection returns valid dict structure."""
    procs = SoftphoneProcessController.get_running_processes()
    assert "eyebeam" in procs
    assert "xlite" in procs
    assert "running" in procs["eyebeam"]
    assert "pid" in procs["eyebeam"]


def test_eyebeam_registry_provisioner_format():
    """Verify EyebeamRegistryProvisioner outputs compliant Windows Registry syntax."""
    reg = EyebeamRegistryProvisioner.generate_reg_content(
        extension="1001",
        password="secretpassword",
        server_ip="192.168.1.150",
        sip_port=5060,
        display_name="Agent 1001",
        auto_answer=True
    )

    assert "Windows Registry Editor Version 5.00" in reg
    assert r"[HKEY_CURRENT_USER\Software\CounterPath\eyeBeam 1.5]" in reg
    assert '"AutoAnswer"=dword:00000001' in reg
    assert '"AutoAnswerSeconds"=dword:00000000' in reg
    assert r"[HKEY_CURRENT_USER\Software\CounterPath\eyeBeam 1.5\Profiles\Profile 1]" in reg
    assert '"DisplayName"="Agent 1001"' in reg
    assert '"UserName"="1001"' in reg
    assert '"Password"="secretpassword"' in reg
    assert '"Domain"="192.168.1.150"' in reg
    assert '"AudioCodecList"="PCMU,PCMA,GSM,iLBC"' in reg


def test_virtual_sip_softphone_packets():
    """Verify VirtualSIPSoftphone builds RFC 3261 compliant REGISTER and Auto-Answer 200 OK packets."""
    v_phone = VirtualSIPSoftphone(
        extension="8388",
        password="secretpass",
        server_ip="192.168.1.200",
        sip_port=5060,
        local_port=5062
    )

    # 1. REGISTER packet
    reg_bytes = v_phone.build_register_packet(cseq=1)
    reg_text = reg_bytes.decode("utf-8")
    assert "REGISTER sip:192.168.1.200:5060 SIP/2.0" in reg_text
    assert "From: <sip:8388@192.168.1.200>" in reg_text
    assert "To: <sip:8388@192.168.1.200>" in reg_text
    assert "CSeq: 1 REGISTER" in reg_text
    assert "Expires: 3600" in reg_text
    assert "Shadow-Voice-Virtual-Eyebeam" in reg_text

    # 2. 200 OK Auto-Answer with SDP
    via = "Via: SIP/2.0/UDP 192.168.1.200:5060;branch=z9hG4bK12345"
    from_hdr = "From: <sip:8600051@192.168.1.200>;tag=998877"
    to_hdr = "To: <sip:8388@192.168.1.200>"
    call_id = "test-call-uuid-8899"
    cseq = "CSeq: 102 INVITE"

    ans_bytes = v_phone.build_auto_answer_200_ok(
        via_header=via,
        from_header=from_hdr,
        to_header=to_hdr,
        call_id=call_id,
        cseq_header=cseq,
        local_rtp_port=16400
    )
    ans_text = ans_bytes.decode("utf-8")
    assert "SIP/2.0 200 OK" in ans_text
    assert "Call-ID: test-call-uuid-8899" in ans_text
    assert "Content-Type: application/sdp" in ans_text
    assert "m=audio 16400 RTP/AVP 0 101" in ans_text
    assert "a=rtpmap:0 PCMU/8000" in ans_text


@pytest.mark.asyncio
async def test_virtual_sip_lifecycle():
    """Verify start and stop methods transition VirtualSIPSoftphone status."""
    v_phone = VirtualSIPSoftphone()
    assert v_phone.status == "UNREGISTERED"

    res_start = await v_phone.start()
    assert res_start["status"] == "REGISTERED"
    assert v_phone.is_running is True

    status = v_phone.get_status()
    assert status["status"] == "REGISTERED"
    assert status["is_running"] is True

    res_stop = await v_phone.stop()
    assert res_stop["status"] == "UNREGISTERED"
    assert v_phone.is_running is False


def test_softphone_api_status_endpoint():
    """Verify GET /api/softphones/status returns installers, processes, and configs."""
    resp = client.get("/api/softphones/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "installers" in data
    assert "eyebeam" in data["installers"]
    assert data["installers"]["eyebeam"]["available"] is True

    assert "processes" in data
    assert "virtual_sip" in data
    assert "configs" in data
    assert "eyebeam" in data["configs"]
    assert bool(data["configs"]["eyebeam"]["extension"]) is True


def test_softphone_api_update_config():
    """Verify PUT /api/softphones/{id} updates extension and credentials."""
    resp = client.put("/api/softphones/eyebeam", json={
        "extension": "1009",
        "secret": "newpassword123",
        "server_ip": "10.0.0.50",
        "sip_port": 5060,
        "auto_answer": True,
        "notes": "Testing softphone update"
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Read back
    status_resp = client.get("/api/softphones/status")
    cfg = status_resp.json()["configs"]["eyebeam"]
    assert cfg["extension"] == "1009"
    assert cfg["server_ip"] == "10.0.0.50"
    assert cfg["auto_answer"] == 1

    # Restore default
    client.put("/api/softphones/eyebeam", json={
        "extension": "1001",
        "secret": "test1001",
        "server_ip": "192.168.1.100",
        "sip_port": 5060,
        "auto_answer": True
    })


def test_softphone_api_generate_and_download_reg():
    """Verify generate-reg and download-reg endpoints."""
    # 1. Generate Reg Content
    res_gen = client.post("/api/softphones/generate-reg", json={
        "extension": "1001",
        "password": "testpassword",
        "server_ip": "192.168.1.100",
        "sip_port": 5060,
        "auto_answer": True
    })
    assert res_gen.status_code == 200
    assert "Windows Registry Editor" in res_gen.json()["reg_content"]

    # 2. Download Reg File
    res_dl = client.get("/api/softphones/download-reg?extension=1001&server_ip=192.168.1.100")
    assert res_dl.status_code == 200
    assert "attachment; filename=eyebeam_vicidial_1001.reg" in res_dl.headers["content-disposition"]
    assert "Windows Registry Editor" in res_dl.text


def test_softphone_api_virtual_register_and_unregister():
    """Verify virtual softphone registration endpoints."""
    res_reg = client.post("/api/softphones/virtual/register", json={
        "extension": "8388",
        "password": "pass",
        "server_ip": "192.168.1.100",
        "sip_port": 5060
    })
    assert res_reg.status_code == 200
    assert res_reg.json()["status"] == "REGISTERED"

    res_unreg = client.post("/api/softphones/virtual/unregister")
    assert res_unreg.status_code == 200
    assert res_unreg.json()["status"] == "UNREGISTERED"


def test_softphone_api_guide():
    """Verify GET /api/softphones/guide returns connection steps."""
    resp = client.get("/api/softphones/guide")
    assert resp.status_code == 200
    data = resp.json()
    assert "steps" in data
    assert len(data["steps"]) >= 4
    assert any("VICIdial" in s["title"] or "Eyebeam" in s["title"] for s in data["steps"])
