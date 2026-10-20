"""
Tests for Dialers & CTI Hub Endpoints
=====================================
Tests:
- Raw dialer configuration retrieval for editing
- Production setup guides & Asterisk dialplan generation
- Inbound dialer call simulation (VICIdial lead dispatch)
- VICIdial Dispo Call URL webhook recording
- Dialer configuration updates via PUT
"""

from fastapi.testclient import TestClient
from shadow_voice.api.app import app

client = TestClient(app)


def test_get_dialers():
    resp = client.get("/api/dialers/")
    assert resp.status_code == 200
    dialers = resp.json()
    assert len(dialers) >= 4
    ids = [d["id"] for d in dialers]
    assert "vicidial" in ids
    assert "asterisk" in ids


def test_get_dialer_raw_config():
    resp = client.get("/api/dialers/vicidial/raw")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "vicidial"
    assert "api_pass" in data


def test_get_dialer_setup_guide_vicidial():
    resp = client.get("/api/dialers/vicidial/guide")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dialer_id"] == "vicidial"
    assert "extensions.conf" in data["asterisk_dialplan"]
    assert "AudioSocket" in data["asterisk_dialplan"]
    assert len(data["vicidial_admin_steps"]) >= 3
    assert "webhook" in data["dispo_webhook_url"]


def test_get_dialer_setup_guide_asterisk():
    resp = client.get("/api/dialers/asterisk/guide")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dialer_id"] == "asterisk"
    assert "AudioSocket" in data["asterisk_dialplan"]


def test_simulate_inbound_dialer_call():
    resp = client.post("/api/dialers/vicidial/simulate-call", json={
        "lead_id": "TEST_LEAD_9981",
        "phone_number": "+1 (312) 555-0188",
        "customer_name": "Sarah Connor",
        "campaign_id": "TEST_SALES"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["lead_id"] == "TEST_LEAD_9981"
    assert "session_id" in data
    assert "greeting" in data
    assert "audio_url" in data["greeting"]


def test_vicidial_webhook():
    # Test GET dispo call URL
    resp_get = client.get("/api/dialers/vicidial/webhook?lead_id=12345&phone=3125550199&dispo=SALE&campaign=SALES_OUT")
    assert resp_get.status_code == 200
    assert resp_get.json()["status"] == "success"

    # Test POST webhook
    resp_post = client.post("/api/dialers/vicidial/webhook", params={
        "lead_id": "67890",
        "phone_number": "3125550188",
        "dispo": "CALLBK"
    })
    assert resp_post.status_code == 200
    assert resp_post.json()["dispo"] == "CALLBK"


def test_update_dialer_config():
    resp = client.put("/api/dialers/vicidial", json={
        "name": "VICIdial Primary Cluster",
        "host": "192.168.1.120",
        "api_url": "http://192.168.1.120/vicidial",
        "api_user": "shadow_vici_user",
        "api_pass": "",
        "campaign_id": "SALES_V2",
        "closer_group": "CLOSERS_POOL",
        "audiosocket_port": 9092,
        "sip_port": 5060,
        "is_active": True,
        "simulated": True,
        "notes": "Configured for live cluster test"
    })
    assert resp.status_code == 200

    raw = client.get("/api/dialers/vicidial/raw").json()
    assert raw["host"] == "192.168.1.120"
    assert raw["campaign_id"] == "SALES_V2"
