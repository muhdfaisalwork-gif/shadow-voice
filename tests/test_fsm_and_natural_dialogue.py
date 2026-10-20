"""Tests for Natural Language Standards (Section 7), Six-Stage FSM, Objections, and Script Deployment."""

import pytest
from shadow_voice.dialogue.natural_rules import NaturalLanguageAuditor
from shadow_voice.dialogue.objections import ObjectionHandler, ObjectionType
from shadow_voice.dialogue.fsm import SalesConversationFSM, Stage
from shadow_voice.dialogue.script_registry import CampaignScriptConfig, ScriptRegistry
from shadow_voice.dialogue.access_control import ScriptDeploymentController


def test_section_7_1_opening_greeting_natural_standard():
    auditor = NaturalLanguageAuditor()

    # Target: Natural human person-to-person opening
    natural_greeting = "Hi, this is Jordan calling from Shadow Voice - do you have a quick minute?"
    passed, violations = auditor.audit_opening(natural_greeting)
    assert passed is True
    assert len(violations) == 0

    # Stiff (banned): robotic AI announcements
    stiff_ai_greeting = "This is an automated call using artificial voice technology on behalf of Shadow Voice."
    passed_stiff, violations_stiff = auditor.audit_opening(stiff_ai_greeting)
    assert passed_stiff is False
    assert any("banned robotic disclosure" in v for v in violations_stiff)


def test_section_7_3_corporate_filler_detection():
    auditor = NaturalLanguageAuditor()
    corporate_filler = "In today's fast-paced environment, we provide cutting-edge revolutionary solutions."
    report = auditor.audit_script(corporate_filler)
    assert report.is_natural is False
    assert report.filler_score >= 2.0


def test_fsm_six_stage_progression():
    fsm = SalesConversationFSM(agent_name="Jordan", company_name="Shadow Voice")

    # 1. Opening greeting
    opening = fsm.get_initial_greeting()
    assert "Jordan" in opening
    assert "Shadow Voice" in opening
    assert "automated" not in opening.lower()
    assert "artificial" not in opening.lower()
    assert fsm.current_stage == Stage.CONNECTION

    # 2. Caller says "Sure, what's up?" -> Qualification
    t1 = fsm.process_turn("Sure, what is this regarding?")
    assert t1.next_stage == Stage.QUALIFICATION
    assert "dialer" in t1.agent_text.lower()

    # 3. Caller says "Yes, we use VICIdial" -> Discovery/Hook
    t2 = fsm.process_turn("We run VICIdial for our agents.")
    assert t2.next_stage == Stage.DISCOVERY_HOOK
    assert "650 milliseconds" in t2.agent_text

    # 4. Caller says "Interesting" -> Offer / Next Step
    t3 = fsm.process_turn("Sounds interesting.")
    assert t3.next_stage == Stage.OFFER_NEXT_STEP
    assert "test" in t3.agent_text.lower()

    # 5. Caller accepts -> Transfer to Live Closer / Tech Lead
    t4 = fsm.process_turn("Yeah, let's do a test tomorrow.")
    assert t4.next_stage == Stage.TRANSFER_DISPOSITION
    assert t4.action == "TRANSFER_WARM"
    assert t4.disposition_code == "SALE"


def test_fsm_dnc_immediate_compliance_path():
    fsm = SalesConversationFSM()
    res = fsm.process_turn("Stop calling me and take me off your list!")
    assert res.action == "DNC"
    assert res.disposition_code == "DNC"
    assert "internal do-not-call list" in res.agent_text.lower()


def test_fsm_human_transfer_path():
    fsm = SalesConversationFSM()
    res = fsm.process_turn("Let me speak to a real person right now.")
    assert res.action == "TRANSFER_WARM"
    assert res.disposition_code == "XFER"


def test_script_deployment_access_control_dual_signoff():
    registry = ScriptRegistry()
    controller = ScriptDeploymentController(registry)

    config = CampaignScriptConfig(
        campaign_id="NEW_SPRING_PROMO",
        version_id="v1.0.0",
        agent_name="Sam",
        company_name="Shadow Voice",
        opening_greeting="Hi, this is Sam with Shadow Voice - do you have a quick second?",
        approved_pricing={"$100"},
        transfer_extension="8400"
    )

    # Missing Dialogue Eng -> rejects
    with pytest.raises(PermissionError):
        controller.deploy_to_production(config, pm_name="Faisal", dialogue_eng_name="")

    # Dual sign-off -> approves
    sign_off = controller.deploy_to_production(config, pm_name="Faisal", dialogue_eng_name="Jordan_Dialogue")
    assert sign_off.pm_name == "Faisal"
    assert sign_off.dialogue_eng_name == "Jordan_Dialogue"
    assert sign_off.audit_signature is not None