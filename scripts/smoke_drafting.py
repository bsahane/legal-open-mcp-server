#!/usr/bin/env python3
"""Smoke-test draft_document over every template in English and Hindi."""

import sys
from typing import Any, cast

sys.path.insert(0, ".")
from legal_mcp_server.src.tools import drafting_tools

FACTS: dict[str, Any] = {
    "writ_petition": {
        "court_place": "BOMBAY",
        "petitioner_name": "A Test",
        "petitioner_address": "Andheri, Mumbai",
        "respondent_name": "State of Maharashtra",
        "respondent_address": "Mantralaya, Mumbai",
        "petition_number": "1234",
        "year": "2026",
        "facts": ["Fact one", "Fact two"],
        "grounds": ["Ground one", "Ground two"],
        "reliefs": ["Quash the order", "Grant costs"],
        "filing_date": "2026-08-16",
        "advocate_name": "Adv. X",
    },
    "civil_appeal": {
        "court_place": "BOMBAY",
        "appellant_name": "A Test",
        "appellant_address": "Andheri, Mumbai",
        "respondent_name": "B Corp",
        "respondent_address": "Nariman Point, Mumbai",
        "appeal_number": "99",
        "year": "2026",
        "impugned_date": "2026-06-01",
        "lower_court": "District Court",
        "lower_court_place": "Thane",
        "lower_court_case_no": "CS 45/2025",
        "facts": ["Fact one", "Fact two"],
        "grounds": ["Ground one"],
        "filing_date": "2026-08-16",
        "advocate_name": "Adv. X",
    },
    "criminal_appeal": {
        "court_place": "BOMBAY",
        "appellant_name": "C Accused",
        "appellant_address": "Pune",
        "respondent_name": "State of Maharashtra",
        "respondent_address": "Mumbai",
        "appeal_number": "77",
        "year": "2026",
        "impugned_date": "2026-06-01",
        "lower_court": "Sessions Court",
        "lower_court_place": "Pune",
        "lower_court_case_no": "SC 12/2025",
        "facts": ["Fact one"],
        "grounds": ["Ground one", "Ground two"],
        "filing_date": "2026-08-16",
        "advocate_name": "Adv. X",
    },
    "slp": {
        "petitioner_name": "D Test",
        "petitioner_address": "Delhi",
        "respondent_name": "Union of India",
        "respondent_address": "New Delhi",
        "petition_number": "SPL 2026/1",
        "year": "2026",
        "impugned_date": "2026-05-05",
        "impugned_court": "High Court of Bombay",
        "impugned_court_place": "Mumbai",
        "impugned_court_case_no": "WP 5678/2024",
        "impugned_disposal": "Dismissed",
        "facts": ["Fact one", "Fact two"],
        "grounds": ["Ground one"],
        "filing_date": "2026-08-16",
        "advocate_name": "Adv. X",
    },
    "ni_138_notice": {
        "sender_name": "Law Firm",
        "sender_address": "Fort, Mumbai",
        "notice_date": "2026-08-16",
        "recipient_name": "E Drawer",
        "recipient_address": "Andheri, Mumbai",
        "client_name": "F Client",
        "client_address": "Borivali, Mumbai",
        "liability_description": "goods supplied under invoice 88 dated 2026-05-01",
        "cheque_number": "123456",
        "cheque_date": "2026-06-01",
        "cheque_amount": 200000,
        "amount_in_words": "Two Lakh Only",
        "drawee_bank": "SBI",
        "drawee_branch": "Andheri",
        "payee_bank": "HDFC",
        "payee_branch": "Fort",
        "presentation_date": "2026-06-02",
        "dishonour_reason": "Insufficient Funds",
        "dishonour_memo_date": "2026-06-03",
        "dishonour_date": "2026-06-03",
    },
    "legal_notice_general": {
        "sender_name": "Law Firm",
        "sender_address": "Fort, Mumbai",
        "notice_date": "2026-08-16",
        "recipient_name": "G Corp",
        "recipient_address": "Pune",
        "subject": "Recovery of dues",
        "client_name": "H Client",
        "client_address": "Thane",
        "facts": ["You owe Rs 5,00,000/-", "You failed to pay despite demands"],
        "legal_basis": "Breach of contract",
        "demands": ["Pay Rs 5,00,000/- within the period stated below"],
        "compliance_days": "15",
        "proposed_proceedings": "civil suit for recovery",
    },
    "reply_to_notice": {
        "sender_name": "I Reply",
        "sender_address": "Pune",
        "reply_date": "2026-08-16",
        "recipient_name": "J Firm",
        "recipient_address": "Mumbai",
        "original_notice_date": "2026-08-01",
        "client_name": "K Client",
        "client_address": "Pune",
        "paragraph_responses": [
            {"paragraph": 1, "reply": "The allegation is denied"},
            {"paragraph": 2, "reply": "The allegation is admitted in part"},
        ],
        "true_facts": ["The goods were defective", "Payment was made"],
    },
    "consumer_complaint": {
        "forum_name": "District Consumer Disputes Redressal Commission",
        "forum_place": "Mumbai",
        "filing_year": "2026",
        "filing_date": "2026-08-16",
        "complainant_name": "L Buyer",
        "complainant_address": "Andheri, Mumbai",
        "opposite_party_name": "M Seller",
        "opposite_party_address": "Chembur, Mumbai",
        "consumer_basis": "purchased the goods for personal use",
        "opposite_party_description": "a dealer in household goods",
        "transaction_date": "2026-04-10",
        "transaction_description": "purchased a washing machine",
        "amount_paid": 18000,
        "facts": ["The machine stopped working within a month"],
        "cause_of_action_date": "2026-05-01",
        "jurisdiction_basis": "the Opposite Party carries on business within the territorial jurisdiction of this Commission",
        "reliefs": ["Replace the machine", "Pay Rs 5,000/- for mental agony"],
        "service_complaint": True,
        "advocate_name": "Adv. X",
    },
    "rti_application": {
        "public_authority": "Municipal Corporation of Greater Mumbai",
        "authority_address": "Fort, Mumbai 400001",
        "application_date": "2026-08-02",
        "information_sought": ["Copy of the building plan for CTS 123"],
        "applicant_name": "B Sahane",
        "applicant_address": "Andheri, Mumbai",
    },
    "affidavit_general": {
        "forum_name": "High Court of Judicature at Bombay",
        "forum_place": "Mumbai",
        "case_year": "2026",
        "petitioner_name": "N Test",
        "respondent_name": "O Corp",
        "deponent_name": "P Deponent",
        "deponent_age": "45",
        "deponent_occupation": "Business",
        "deponent_address": "Andheri, Mumbai",
        "deponent_capacity": "the petitioner",
        "statements": ["I am the petitioner", "The facts are true"],
        "affidavit_date": "2026-08-16",
    },
}

for key, params in FACTS.items():
    for lang in ("en", "hi"):
        r = drafting_tools.draft_document(key, cast(dict, params), language=lang)
        status = r.get("status")
        if status != "success":
            print(f"FAIL {key}/{lang}: {status} :: {r.get('message', r.get('error'))}")
        else:
            assert "{{" not in r["draft"] or "{" not in r["draft"], (
                f"jinja leftovers in {key}/{lang}"
            )
            print(
                f"OK   {key}/{lang}: {len(r['draft'])} chars, checklist={len(r['checklist'])}"
            )

print("--- translate_document ---")
r = drafting_tools.draft_document(
    "ni_138_notice", dict(FACTS["ni_138_notice"]), language="en"
)
t = drafting_tools.translate_document(r["draft"], target_language="hi")
print("sentences_translated:", t.get("sentences_translated"))
if "महोदय" not in t.get("translated_draft", ""):
    print("FAIL: hindi not applied")
else:
    print("OK translate_document")

print("--- get_document_languages ---")
for key in ("writ_petition", "ni_138_notice"):
    r = drafting_tools.get_document_languages(key)
    print(key, r.get("languages"), r.get("status"))
