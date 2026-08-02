"""Concordance between the old and new Indian criminal codes.

On 1 July 2024 three statutes replaced the backbone of Indian criminal law:

===========================================  ===========================================
Repealed                                     Replacement
===========================================  ===========================================
Indian Penal Code, 1860                      Bharatiya Nyaya Sanhita, 2023
Code of Criminal Procedure, 1973             Bharatiya Nagarik Suraksha Sanhita, 2023
Indian Evidence Act, 1872                    Bharatiya Sakshya Adhiniyam, 2023
===========================================  ===========================================

The governing code is fixed by the **date of the offence**, not the date of the
advice. An offence committed on 30 June 2024 is still an IPC offence and is
tried under the CrPC; one committed on 1 July 2024 is a BNS offence tried under
the BNSS. Getting this wrong produces a charge under a provision that did not
exist at the time, so :func:`applicable_code` is the first question these tools
answer.

The concordance below is a curated subset covering the provisions that come up
most in practice. It is not the complete official mapping, and every lookup
reports whether the pairing is in the table rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

#: The date the three new codes came into force.
NEW_CODES_COMMENCEMENT = date(2024, 7, 1)

CODE_IPC = "Indian Penal Code, 1860"
CODE_BNS = "Bharatiya Nyaya Sanhita, 2023"
CODE_CRPC = "Code of Criminal Procedure, 1973"
CODE_BNSS = "Bharatiya Nagarik Suraksha Sanhita, 2023"
CODE_EVIDENCE = "Indian Evidence Act, 1872"
CODE_BSA = "Bharatiya Sakshya Adhiniyam, 2023"

CODE_PAIRS = {
    "penal": (CODE_IPC, CODE_BNS),
    "procedure": (CODE_CRPC, CODE_BNSS),
    "evidence": (CODE_EVIDENCE, CODE_BSA),
}


@dataclass
class Mapping:
    """One old-section to new-section correspondence."""

    domain: str
    old_code: str
    old_section: str
    new_code: str
    new_section: str
    subject: str
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        """Serialise for MCP tool output."""
        return {
            "domain": self.domain,
            "old_code": self.old_code,
            "old_section": self.old_section,
            "new_code": self.new_code,
            "new_section": self.new_section,
            "subject": self.subject,
            "note": self.note,
        }


def _m(
    domain: str, old: str, new: str, subject: str, note: Optional[str] = None
) -> Mapping:
    old_code, new_code = CODE_PAIRS[domain]
    return Mapping(domain, old_code, old, new_code, new, subject, note)


# IPC -> BNS. Curated subset of the most-used offences.
_PENAL: List[Mapping] = [
    _m(
        "penal",
        "34",
        "3(5)",
        "Acts done by several persons in furtherance of common intention",
    ),
    _m("penal", "120B", "61(2)", "Criminal conspiracy"),
    _m("penal", "141", "189(1)", "Unlawful assembly"),
    _m("penal", "143", "189(2)", "Punishment for unlawful assembly"),
    _m("penal", "147", "191(2)", "Rioting"),
    _m("penal", "153A", "196", "Promoting enmity between groups"),
    _m("penal", "279", "281", "Rash driving on a public way"),
    _m("penal", "299", "100", "Culpable homicide"),
    _m("penal", "300", "101", "Murder"),
    _m("penal", "302", "103", "Punishment for murder"),
    _m(
        "penal",
        "304",
        "105",
        "Punishment for culpable homicide not amounting to murder",
    ),
    _m("penal", "304A", "106", "Causing death by negligence"),
    _m("penal", "304B", "80", "Dowry death"),
    _m("penal", "306", "108", "Abetment of suicide"),
    _m("penal", "307", "109", "Attempt to murder"),
    _m("penal", "319", "114", "Hurt"),
    _m("penal", "320", "116", "Grievous hurt"),
    _m("penal", "323", "115(2)", "Punishment for voluntarily causing hurt"),
    _m("penal", "324", "118(1)", "Voluntarily causing hurt by dangerous weapons"),
    _m("penal", "325", "117(2)", "Punishment for voluntarily causing grievous hurt"),
    _m("penal", "326A", "124(1)", "Voluntarily causing grievous hurt by acid attack"),
    _m("penal", "354", "74", "Assault on a woman with intent to outrage her modesty"),
    _m("penal", "354A", "75", "Sexual harassment"),
    _m("penal", "354D", "78", "Stalking"),
    _m("penal", "363", "137(2)", "Kidnapping"),
    _m("penal", "375", "63", "Rape"),
    _m("penal", "376", "64", "Punishment for rape"),
    _m("penal", "378", "303(1)", "Theft"),
    _m("penal", "379", "303(2)", "Punishment for theft"),
    _m("penal", "383", "308(1)", "Extortion"),
    _m("penal", "384", "308(2)", "Punishment for extortion"),
    _m("penal", "390", "309(1)", "Robbery"),
    _m("penal", "391", "310(1)", "Dacoity"),
    _m("penal", "403", "314", "Dishonest misappropriation of property"),
    _m("penal", "405", "316(1)", "Criminal breach of trust"),
    _m("penal", "406", "316(2)", "Punishment for criminal breach of trust"),
    _m(
        "penal", "409", "316(5)", "Criminal breach of trust by public servant or banker"
    ),
    _m("penal", "415", "318(1)", "Cheating"),
    _m("penal", "417", "318(2)", "Punishment for cheating"),
    _m(
        "penal",
        "420",
        "318(4)",
        "Cheating and dishonestly inducing delivery of property",
    ),
    _m("penal", "425", "324(1)", "Mischief"),
    _m("penal", "441", "329(1)", "Criminal trespass"),
    _m("penal", "447", "329(3)", "Punishment for criminal trespass"),
    _m("penal", "448", "329(4)", "Punishment for house-trespass"),
    _m("penal", "463", "336(1)", "Forgery"),
    _m("penal", "465", "336(2)", "Punishment for forgery"),
    _m("penal", "468", "336(3)", "Forgery for purpose of cheating"),
    _m("penal", "471", "340(2)", "Using as genuine a forged document"),
    _m("penal", "498A", "85", "Cruelty to a married woman by husband or his relatives"),
    _m("penal", "499", "356(1)", "Defamation"),
    _m("penal", "500", "356(2)", "Punishment for defamation"),
    _m("penal", "503", "351(1)", "Criminal intimidation"),
    _m("penal", "506", "351(2)", "Punishment for criminal intimidation"),
    _m(
        "penal",
        "509",
        "79",
        "Word or gesture intended to insult the modesty of a woman",
    ),
]

# CrPC -> BNSS. Curated subset of the most-used procedural provisions.
_PROCEDURE: List[Mapping] = [
    _m("procedure", "41", "35", "When police may arrest without warrant"),
    _m("procedure", "41A", "35(3)", "Notice of appearance before police officer"),
    _m("procedure", "50", "47", "Person arrested to be informed of grounds of arrest"),
    _m("procedure", "91", "94", "Summons to produce document or other thing"),
    _m(
        "procedure",
        "125",
        "144",
        "Order for maintenance of wives, children and parents",
    ),
    _m(
        "procedure",
        "144",
        "163",
        "Power to issue order in urgent cases of nuisance or apprehended danger",
    ),
    _m("procedure", "154", "173", "Information in cognizable cases (FIR)"),
    _m(
        "procedure",
        "156",
        "175",
        "Police officer's power to investigate cognizable case",
    ),
    _m("procedure", "161", "180", "Examination of witnesses by police"),
    _m("procedure", "164", "183", "Recording of confessions and statements"),
    _m(
        "procedure",
        "167",
        "187",
        "Procedure when investigation cannot be completed in 24 hours",
    ),
    _m(
        "procedure",
        "173",
        "193",
        "Report of police officer on completion of investigation",
    ),
    _m("procedure", "190", "210", "Cognizance of offences by Magistrates"),
    _m(
        "procedure",
        "197",
        "218",
        "Prosecution of Judges and public servants - sanction",
    ),
    _m(
        "procedure",
        "200",
        "223",
        "Examination of complainant",
        "BNSS adds a mandatory opportunity of hearing to the accused before "
        "cognizance is taken on a complaint - a substantive change, not a "
        "renumbering.",
    ),
    _m("procedure", "227", "262", "Discharge"),
    _m("procedure", "228", "263", "Framing of charge"),
    _m("procedure", "239", "268", "When accused shall be discharged (warrant cases)"),
    _m("procedure", "313", "351", "Power to examine the accused"),
    _m(
        "procedure",
        "319",
        "358",
        "Power to proceed against other persons appearing to be guilty",
    ),
    _m("procedure", "320", "359", "Compounding of offences"),
    _m("procedure", "354", "392", "Language and contents of judgment"),
    _m("procedure", "374", "415", "Appeals from convictions"),
    _m("procedure", "397", "438", "Calling for records to exercise powers of revision"),
    _m("procedure", "436", "478", "In what cases bail to be taken"),
    _m(
        "procedure",
        "436A",
        "479",
        "Maximum period of detention of undertrial prisoner",
        "BNSS 479 is stricter for repeat offenders and more generous for "
        "first-time offenders than CrPC 436A.",
    ),
    _m(
        "procedure",
        "437",
        "480",
        "When bail may be taken in case of non-bailable offence",
    ),
    _m(
        "procedure",
        "438",
        "482",
        "Direction for grant of bail to person apprehending arrest",
    ),
    _m(
        "procedure",
        "439",
        "483",
        "Special powers of High Court or Court of Session regarding bail",
    ),
    _m(
        "procedure",
        "451",
        "497",
        "Order for custody and disposal of property pending trial",
    ),
    _m("procedure", "482", "528", "Saving of inherent powers of High Court"),
]

# Evidence Act -> BSA. Curated subset.
_EVIDENCE: List[Mapping] = [
    _m("evidence", "3", "2", "Interpretation clause"),
    _m(
        "evidence",
        "5",
        "3",
        "Evidence may be given of facts in issue and relevant facts",
    ),
    _m("evidence", "8", "6", "Motive, preparation and previous or subsequent conduct"),
    _m("evidence", "17", "24", "Admission defined"),
    _m("evidence", "24", "22", "Confession caused by inducement, threat or promise"),
    _m("evidence", "25", "23(1)", "Confession to police officer not to be proved"),
    _m(
        "evidence",
        "27",
        "23(2)",
        "How much of information received from accused may be proved",
    ),
    _m(
        "evidence",
        "32",
        "26",
        "Statements by persons who cannot be called as witnesses",
    ),
    _m("evidence", "45", "39", "Opinion of experts"),
    _m("evidence", "62", "57", "Primary evidence"),
    _m("evidence", "63", "58", "Secondary evidence"),
    _m(
        "evidence",
        "65A",
        "63",
        "Special provisions as to evidence relating to electronic record",
    ),
    _m(
        "evidence",
        "65B",
        "63",
        "Admissibility of electronic records",
        "BSA 63 merges the old 65A and 65B and revises the certificate "
        "requirement; do not assume the old form is sufficient.",
    ),
    _m("evidence", "101", "104", "Burden of proof"),
    _m("evidence", "106", "109", "Burden of proving fact especially within knowledge"),
    _m(
        "evidence",
        "113A",
        "119",
        "Presumption as to abetment of suicide by a married woman",
    ),
    _m("evidence", "113B", "118", "Presumption as to dowry death"),
    _m("evidence", "114", "120", "Court may presume existence of certain facts"),
]

ALL_MAPPINGS: List[Mapping] = _PENAL + _PROCEDURE + _EVIDENCE


def _key(section: str) -> str:
    """Canonicalise a section number for lookup."""
    return str(section).strip().lower().replace(" ", "").replace("-", "").rstrip(".")


_OLD_INDEX: Dict[str, List[Mapping]] = {}
_NEW_INDEX: Dict[str, List[Mapping]] = {}
for _mapping in ALL_MAPPINGS:
    _OLD_INDEX.setdefault(_key(_mapping.old_section), []).append(_mapping)
    _NEW_INDEX.setdefault(_key(_mapping.new_section), []).append(_mapping)
    # Also index the bare section number so "318" finds "318(4)".
    _bare = _key(_mapping.new_section).split("(")[0]
    if _bare != _key(_mapping.new_section):
        _NEW_INDEX.setdefault(_bare, []).append(_mapping)


def applicable_code(offence_date: date) -> Dict[str, object]:
    """Determine which criminal codes govern an offence on a given date.

    Args:
        offence_date: The date the offence was committed.

    Returns:
        Dict naming the governing penal, procedural and evidence statutes, and
        explaining why.
    """
    if offence_date >= NEW_CODES_COMMENCEMENT:
        return {
            "offence_date": offence_date.isoformat(),
            "regime": "new",
            "penal_code": CODE_BNS,
            "procedure_code": CODE_BNSS,
            "evidence_act": CODE_BSA,
            "reason": (
                f"The offence date is on or after {NEW_CODES_COMMENCEMENT.isoformat()}, "
                "so the BNS, BNSS and BSA apply."
            ),
        }

    return {
        "offence_date": offence_date.isoformat(),
        "regime": "old",
        "penal_code": CODE_IPC,
        "procedure_code": CODE_CRPC,
        "evidence_act": CODE_EVIDENCE,
        "reason": (
            f"The offence date is before {NEW_CODES_COMMENCEMENT.isoformat()}, so the "
            "IPC, CrPC and Evidence Act continue to apply to it, even though those "
            "statutes have since been repealed. Charging under the BNS for a "
            "pre-commencement offence would be wrong."
        ),
        "caveat": (
            "Procedure is not always frozen with the offence date. Investigations "
            "and trials pending on 1 July 2024 continue under the CrPC by virtue of "
            "the BNSS savings provision, but steps commenced afterwards may attract "
            "the new procedure. Check the savings clause for the specific step."
        ),
    }


def map_old_to_new(section: str, domain: Optional[str] = None) -> List[Mapping]:
    """Find the new-code equivalent of an old-code section.

    Args:
        section: Section number under the IPC, CrPC or Evidence Act.
        domain: Optional restriction to ``penal``, ``procedure`` or ``evidence``.

    Returns:
        Matching mappings, empty if the section is not in the curated table.
    """
    found = _OLD_INDEX.get(_key(section), [])
    if domain:
        found = [m for m in found if m.domain == domain]
    return found


def map_new_to_old(section: str, domain: Optional[str] = None) -> List[Mapping]:
    """Find the old-code equivalent of a new-code section.

    Args:
        section: Section number under the BNS, BNSS or BSA.
        domain: Optional restriction to ``penal``, ``procedure`` or ``evidence``.

    Returns:
        Matching mappings, empty if the section is not in the curated table.
    """
    found = _NEW_INDEX.get(_key(section), [])
    if domain:
        found = [m for m in found if m.domain == domain]
    return found


def search_by_subject(subject: str, limit: int = 10) -> List[Mapping]:
    """Find mappings whose subject matches a description of the offence.

    Args:
        subject: Words describing the offence or procedural step.
        limit: Maximum mappings to return.

    Returns:
        Matching mappings, best first.
    """
    terms = [t for t in subject.lower().split() if len(t) > 2]
    if not terms:
        return []

    scored = []
    for mapping in ALL_MAPPINGS:
        text = mapping.subject.lower()
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, mapping))

    scored.sort(key=lambda pair: (-pair[0], pair[1].old_section))
    return [m for _, m in scored[:limit]]


def coverage() -> Dict[str, int]:
    """How many mappings the curated concordance holds, by domain."""
    return {
        "penal": len(_PENAL),
        "procedure": len(_PROCEDURE),
        "evidence": len(_EVIDENCE),
        "total": len(ALL_MAPPINGS),
    }
