"""Indian-language translations for legal document static text.

The drafting templates (``templates/documents/*.j2``) render user-supplied
facts in the chosen language.  This module holds translations of *static*
text -- headings, salutations, standard clauses -- so the same template
can render in any supported language.  User-supplied content (party names,
facts, amounts) passes through unchanged.

Usage inside a Jinja2 template::

    {{ t('dear_sir_madam', language) }}
    {{ t('under_instructions', language) }}

``t`` is registered as a Jinja2 global by the function
:func:`legal_mcp_server.src.tools.drafting_tools._environment`.

Adding a new phrase
-------------------
1.  Add the key to :data:`_TRANSLATIONS` with at least an ``"en"`` entry.
2.  Reference it in the template as ``{{ t('phrase_key', language) }}``.
3.  Community contributors can add translations for any language without
    touching templates or other Python logic.
"""

from __future__ import annotations

from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Supported languages
# ---------------------------------------------------------------------------
SUPPORTED_LANGUAGES: Dict[str, Dict[str, str]] = {
    "en": {"name": "English", "native": "English"},
    "hi": {"name": "Hindi", "native": "हिंदी"},
    "mr": {"name": "Marathi", "native": "मराठी"},
    "ta": {"name": "Tamil", "native": "தமிழ்"},
    "te": {"name": "Telugu", "native": "తెలుగు"},
}

DEFAULT_LANGUAGE = "en"


# ---------------------------------------------------------------------------
# Translation dictionary
#
# Keys are stable phrase identifiers (snake_case).  Values map language code
# to the translated string.  Falls back to English when a phrase has no
# entry for the requested language, so templates render fully in English
# until a translation is provided rather than failing or showing a raw key.
# ---------------------------------------------------------------------------
_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    # Salutations
    "dear_sir_madam": {
        "en": "Sir/Madam,",
        "hi": "महोदय/सुश्री,",
    },
    "to": {
        "en": "To,",
        "hi": "से,",
    },
    "yours_faithfully": {
        "en": "Yours faithfully,",
        "hi": "आपका वफादार,",
    },
    "yours_sincerely": {
        "en": "Yours sincerely,",
        "hi": "आपका सन्मानपूर्वक,",
    },
    "copy_to_client": {
        "en": "Copy to: My client, for record.",
        "hi": "प्रति: मेरे मुवक्किल के लिए रिकॉर्ड।",
    },
    # Header labels
    "ref": {
        "en": "Ref:",
        "hi": "संदर्भ:",
    },
    "date_label": {
        "en": "Date:",
        "hi": "दिनांक:",
    },
    "sub": {
        "en": "Sub:",
        "hi": "विषय:",
    },
    "registered_post_ad": {
        "en": "BY REGISTERED POST A.D.",
        "hi": "पंजीकृत डाक द्वारा",
    },
    "and_by_email": {
        "en": "AND BY EMAIL",
        "hi": "और ईमेल द्वारा",
    },
    "enclosures": {
        "en": "Enclosures:",
        "hi": "संलग्नक:",
    },
    "copy_to_opposite_party": {
        "en": "Copy to: Opposite Party / Respondent, for information.",
        "hi": "प्रति: प्रतिपक्षी पक्ष / उत्तरदाता, जानकारी के लिए।",
    },
    # NI Act notice body (paragraphs 1-7)
    "under_instructions": {
        "en": "Under instructions from and on behalf of my client",
        "hi": "मेरे मुवक्किल की आदेशों के अनुसार और उनकी ओर से",
    },
    "hereinafter_client": {
        'en': '(hereinafter "my client")',
        'hi': '(इसके बाद "मेरा मुवक्किल")',
    },
    "that_you_are_acquainted": {
        "en": "That you are well acquainted with my client and the "
        "transactions between you and my client.",
        "hi": "यह कि आप मेरे मुवक्किल से और आपके बीच के लेन-देन से "
        "अच्छी तरह से परिचित हैं।",
    },
    "that_legally_liable_to_pay": {
        "en": "That you were and continue to be legally liable to pay a "
        "sum of Rs {{ amount_inr }}/- (Rupees {{ amount_words }} "
        "only) to my client.",
        "hi": "यह कि आप मेरे मुवक्किल को रु. {{ amount_inr }}/- (शब्दों "
        "में {{ amount_words }} मात्र) भुगतान करने के लिए कानूनी "
        "रूप से उत्तरदायी थे और अभी भी हैं।",
    },
    "cheque_issued": {
        "en": "That in discharge of the said legally enforceable debt and "
        "liability, you issued to my client cheque bearing No. "
        "{{ cheque_number }} dated {{ cheque_date }} for a sum of "
        "Rs {{ cheque_amount_inr }}/- drawn on {{ drawee_bank }}, "
        "{{ drawee_branch }} branch{{ drawer_account_clause }} "
        '(hereinafter "the said cheque").',
        "hi": "यह कि उक्त कानूनी रूप से प्रवर्तनीय ऋण और दायित्व की "
        "अदायगी में आपने मेरे मुवक्किल को रु. {{ cheque_amount_inr }}/- "
        "का धनादेश जारी किया जिसका संख्या {{ cheque_number }} तिथि "
        "{{ cheque_date }} है, जो {{ drawee_bank }}, {{ drawee_branch }} "
        "शाखा पर आयोजित है{{ drawer_account_clause }}।",
    },
    "presented_for_encashment": {
        "en": "That my client presented the said cheque for encashment "
        "through {{ payee_bank }}, {{ payee_branch }} branch, on "
        "{{ presentation_date }}.",
        "hi": "यह कि मेरे मुवक्किल ने उक्त धनादेश को {{ payee_bank }}, "
        "{{ payee_branch }} शाखा के द्वारा {{ presentation_date }} को "
        "नगदिकरण के लिए प्रस्तुत किया।",
    },
    "returned_unpaid": {
        'en': 'That the said cheque was returned unpaid by the drawee bank '
        'with the endorsement "{{ dishonour_reason }}", and the said '
        "return memo dated {{ dishonour_memo_date }} was received by my "
        "client on {{ dishonour_date }}.",
        'hi': 'यह कि उक्त धनादेश को प्राप्तकर्ता बैंक द्वारा '
        '"{{ dishonour_reason }}" कहकर बिना भुगतान वापस कर दिया गया, '
        "और तारीख {{ dishonour_memo_date }} का वह वापसी मेमो मेरे "
        "मुवक्किल को {{ dishonour_date }} को प्राप्त हुआ।",
    },
    "dishonour_is_offence": {
        "en": "That the dishonour of the said cheque is on account of your "
        "act and omission, and constitutes an offence punishable under "
        "Section 138 of the Negotiable Instruments Act, 1881.",
        "hi": "यह कि उक्त धनादेश की अवज्ञा आपके कार्य और अकरण के कारण "
        "हुई है, और वह धनादेश अधिनियम, 1881 की धारा 138 के तहत "
        "दंडनीय अपराध है।",
    },
    "therefore_call_upon": {
        "en": "I therefore call upon you, through this notice, to pay to "
        "my client the sum of Rs {{ amount_inr }}/- (Rupees "
        "{{ amount_words }} only)",
        "hi": "अतः मैं आपको इस नोटिस के द्वारा कहता हूं कि मेरे मुवक्किल "
        "को रु. {{ amount_inr }}/- (शब्दों में {{ amount_words }} "
        "मात्र) भुगतान करें",
    },
    "fifteen_days": {
        "en": "FIFTEEN (15) DAYS",
        "hi": "पंद्रह (15) दिन",
    },
    "within_days_failing": {
        "en": "from the date of receipt of this notice, failing which my "
        "client shall be constrained to initiate criminal proceedings "
        "against you under Section 138 of the Negotiable Instruments "
        "Act, 1881 before the competent court, entirely at your risk as "
        "to costs and consequences.",
        "hi": "इस नोटिस की प्राप्ति की तारीख से, अन्यथा मेरा मुवक्किल "
        "आपके खिलाफ आपराधिक कार्यवाही शुरू करने के लिए विवश हो "
        "जाएगा।",
    },
    # Pleading / petition headers
    "in_the_high_court": {
        "en": "IN THE HIGH COURT OF JUDICATURE AT {{ court_place }}",
        "hi": "{{ court_place }} में उच्च न्यायालय में",
    },
    "in_the_supreme_court": {
        "en": "IN THE SUPREME COURT OF INDIA",
        "hi": "भारत के उच्चतम न्यायालय में",
    },
    "appellate_jurisdiction": {
        "en": "{{ jurisdiction_type }} APPELLATE JURISDICTION",
        "hi": "{{ jurisdiction_type }} अपील न्यायाधिकरण",
    },
    "appellate_original_jurisdiction": {
        "en": "{{ jurisdiction_type }} JURISDICTION",
        "hi": "{{ jurisdiction_type }} न्यायाधिकरण",
    },
    "original_jurisdiction": {
        "en": "ORIGINAL JURISDICTION",
        "hi": "मूल न्यायाधिकरण",
    },
    "writ_petition_no": {
        "en": "WRIT PETITION NO. {{ petition_number }} OF {{ year }}",
        "hi": "रिट याचिका संख्या {{ petition_number }} वर्ष {{ year }}",
    },
    "civil_appeal_no": {
        "en": "CIVIL APPEAL NO. {{ appeal_number }} OF {{ year }}",
        "hi": "नागरिक अपील संख्या {{ appeal_number }} वर्ष {{ year }}",
    },
    "criminal_appeal_no": {
        "en": "CRIMINAL APPEAL NO. {{ appeal_number }} OF {{ year }}",
        "hi": "आपराधिक अपील संख्या {{ appeal_number }} वर्ष {{ year }}",
    },
    "between": {
        "en": "BETWEEN",
        "hi": "बीच",
    },
    "and": {
        "en": "AND",
        "hi": "और",
    },
    "petitioner_label": {
        "en": "... Petitioner(s) / Appellant(s)",
        "hi": "... याचिकाकर्ता / अपीलकर्ता",
    },
    "respondent_label": {
        "en": "... Respondent / Opposite Party",
        "hi": "... उत्तरदाता / प्रतिपक्षी",
    },
    "under_articles": {
        "en": "UNDER ARTICLES 226 AND 227 OF THE CONSTITUTION OF INDIA",
        "hi": "भारत के संविधान के अनुच्छेद 226 और 227 के तहत",
    },
    "most_respectfully_showeth": {
        "en": "MOST RESPECTFULLY SHOWETH:",
        "hi": "सादर दर्शाते हैं:",
    },
    "the_facts_are_as_under": {
        "en": "The facts of the case are as under:",
        "hi": "मामले के तथ्य निम्नलिखित हैं:",
    },
    "grounds_for_relief": {
        "en": "The grounds for the relief claimed are as under:",
        "hi": "दावा किए गए राहत के आधार निम्नलिखित हैं:",
    },
    "prayer_heading": {
        "en": "PRAYER",
        "hi": "प्रार्थना",
    },
    "prays_relief": {
        "en": "It is, therefore, most humbly prayed that this Hon'ble "
        "Court may be pleased to:",
        "hi": "अतः सादर प्रार्थना है कि इस आदरणीय अदालत से कृपया:",
    },
    "prayer_bullet": {
        "en": "{{ item }}; and",
        "hi": "{{ item }}; तथा",
    },
    "and_pass_such_other": {
        "en": "And pass such other order or orders as this Hon'ble Court "
        "may deem fit and proper in the circumstances of the case.",
        "hi": "और मामले की परिस्थितियों में इस आदरणीय अदालत को उचित "
        "और युक्त मानने वाला अन्य कोई आदेश भी जारी करें।",
    },
    # Consumer complaint
    "consumer_complaint_no": {
        "en": "CONSUMER COMPLAINT NO. ________ OF {{ filing_year }}",
        "hi": "उपभोक्ता शिकायत संख्या ________ वर्ष {{ filing_year }}",
    },
    "complaint_under_section": {
        "en": "COMPLAINT UNDER SECTION {{ section }} OF THE {{ act }}",
        "hi": "{{ act }} की धारा {{ section }} के तहत शिकायत",
    },
    "complainant_is_consumer": {
        "en": "That the Complainant is a consumer within the meaning of "
        "Section 2(7) of the Consumer Protection Act, 2019, having "
        "{{ consumer_basis }}.",
        "hi": "यह कि शिकायतकर्ता उपभोक्ता सुरक्षा अधिनियम, 2019 की "
        "धारा 2(7) के अर्थ में उपभोक्ता है, जिसकी {{ consumer_basis }} है।",
    },
    "opposite_party_is": {
        "en": "That the Opposite Party is {{ description }} and is a "
        "{{ party_type }} within the meaning of the Act.",
        "hi": "यह कि प्रतिपक्षी पक्ष {{ description }} है और अधिनियम के "
        "अर्थ में {{ party_type }} है।",
    },
    "deficiency_in_service": {
        "en": "deficiency in service within the meaning of Section 2(11) of "
        "the Consumer Protection Act, 2019",
        "hi": "सेवा में कमी उपभोक्ता सुरक्षा अधिनियम, 2019 की धारा 2(11) "
        "के अर्थ में",
    },
    "defective_goods_unfair_trade": {
        "en": "sale of defective goods and unfair trade practice within the "
        "meaning of Sections 2(10) and 2(47) of the Consumer Protection Act, "
        "2019",
        "hi": "दोषपूर्ण सामान की बिक्री और अन्यायपूर्ण व्यापारिक प्रथा "
        "उपभोक्ता सुरक्षा अधिनियम, 2019 की धाराओं 2(10) और 2(47) के अर्थ में",
    },
    "advocate_for_complainant": {
        "en": "Advocate for the Complainant",
        "hi": "शिकायतकर्ता के वकील",
    },
    # Reply to notice
    "reply_to_notice_subject": {
        "en": "Reply to your notice dated {{ original_notice_date }}",
        "hi": "आपकी तारीख {{ original_notice_date }} की नोटिस का उत्तर",
    },
    "reply_to_notice_intro": {
        "en": "I reply to your notice dated",
        "hi": "मैं आपकी तारीख की नोटिस का उत्तर देता हूं",
    },
    # Verification
    "verification": {
        "en": "VERIFICATION",
        "hi": "सत्यापन",
    },
    "verification_body": {
        "en": "I, {{ deponent_name }}, {{ deponent_capacity }}, do hereby "
        "verify that the contents of paras {{ para_range }} of the "
        "foregoing {{ doc_type }} are true and correct to my knowledge "
        "and belief and nothing material has been concealed therefrom. "
        "I further declare that this verification is made on the basis "
        "of documents maintained in the ordinary course of business "
        "which I believe to be true.",
        "hi": "मैं, {{ deponent_name }}, {{ deponent_capacity }} यहां "
        "सत्यापित करता/करती हूं कि पूर्वोक्त {{ doc_type }} के "
        "{{ para_range }} पैराग्राफ की सामग्री मेरी जानकारी और विश्वास "
        "के अनुसार सत्य और सही है और उसमें से कोई भी सारी बात छुपाई "
        "नहीं गई है। मैं यह और घोषणा करता/करती हूं कि यह सत्यापन "
        "व्यवसाय के साधारण क्रम में रखे गए दस्तावेजों के आधार पर "
        "किया गया है जो मेरी विश्वास के अनुसार सत्य हैं।",
    },
    "solemnly_affirm": {
        "en": "Solemnly affirmed at {{ place }} on this {{ day }} day of "
        "{{ month }}, {{ year }}.",
        "hi": "साक्षात् इस {{ day }} दिन {{ month }}, {{ year }} को "
        "{{ place }} में सत्यापित किया गया।",
    },
    "deponent_signature": {
        "en": "Signature of the Deponent",
        "hi": "शपथग्राही के हस्ताक्षर",
    },
    "advocate_for_petitioner": {
        "en": "Advocate for the Petitioner",
        "hi": "याचिकाकर्ता के वकील",
    },
    "advocate_for_respondent": {
        "en": "Advocate for the Respondent",
        "hi": "उत्तरदाता के वकील",
    },
    # Miscellaneous
    "application_title": {
        "en": "APPLICATION UNDER SECTION {{ section }} OF {{ act_name }}",
        "hi": "{{ act_name }} की धारा {{ section }} के तहत आवेदन",
    },
    "prays_for_order": {
        "en": "Prays for the following orders:",
        "hi": "निम्नलिखित आदेशों की प्रार्थना करता है:",
    },
    "interim_relief": {
        "en": "INTERIM RELIEF",
        "hi": "अंतरिम राहत",
    },
    "final_relief": {
        "en": "RELIEFS PRAYED",
        "hi": "दावा की राहतें",
    },
    "jurisdiction_clause": {
        "en": "Jurisdiction:",
        "hi": "क्षेत्राधिकार:",
    },
    "cause_of_action_arises": {
        "en": "The cause of action for this application arose within the "
        "jurisdiction of this Hon'ble Court on {{ date }}.",
        "hi": "इस आवेदन का कारण इस आदरणीय अदालत के क्षेत्राधिकार "
        "में {{ date }} को उत्पन्न हुआ।",
    },
}


def t(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Return the translation for *key* in *language*.

    Falls back to English when the requested language has no entry for the
    key, so templates render fully in English until a translation is
    provided rather than failing or showing a raw key name.

    Args:
        key: Stable phrase identifier (snake_case).  Must exist in at least
             the ``"en"`` entry.
        language: ISO 639-1 language code.  See :data:`SUPPORTED_LANGUAGES`.

    Returns:
        The translated string, or the English fallback.
    """
    lang_dict = _TRANSLATIONS.get(key, {})
    return lang_dict.get(language) or lang_dict.get("en") or key


def get_supported_languages() -> Dict[str, Dict[str, str]]:
    """Return the language registry for tool-facing responses."""
    return dict(SUPPORTED_LANGUAGES)


def translation_entries() -> Dict[str, Dict[str, str]]:
    """Return the raw translation dictionary for tooling (e.g. rule-based
    translation of already-rendered drafts).

    Keys are stable phrase identifiers; values map language code to the
    translated string, with ``{{ name }}`` placeholders for user-supplied
    values.
    """
    return _TRANSLATIONS


def validate_language(language: Optional[str]) -> str:
    """Normalise a language code, returning :data:`DEFAULT_LANGUAGE` on
    missing or unknown input.

    Accepts bare codes (``"hi"``) and tags (``"hi-IN"``).
    """
    if not language:
        return DEFAULT_LANGUAGE
    lang = language.strip().lower()
    if lang in SUPPORTED_LANGUAGES:
        return lang
    prefix = lang[:2]
    return prefix if prefix in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
