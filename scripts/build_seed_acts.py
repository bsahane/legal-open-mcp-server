#!/usr/bin/env python3
"""Generate the hand-curated partial Acts under ``data/acts_seed/``.

Several Acts that matter constantly in Indian practice - the Contract Act, the
Limitation Act, the three new criminal codes, the Constitution - are not in any
open section-level JSON dataset. Rather than scrape them at query time or leave
them out, this script writes curated extracts of their most-used provisions.

Every section written here is marked ``"text_kind": "summary"``. The text is a
faithful summary of the provision, not its authentic wording, and the loader
carries that distinction out to the tool response so a summary can never be
quoted as the words of the statute. Each entry carries the India Code URL for
the authentic text.

Run ``python scripts/build_seed_acts.py`` then ``python scripts/fetch_corpus.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "acts_seed"


def act(
    slug: str,
    title: str,
    short_title: str,
    year: int,
    act_number: str,
    aliases: List[str],
    url: str,
    sections: List[Dict[str, Any]],
    note: str | None = None,
) -> Dict[str, Any]:
    """Assemble one curated Act file."""
    return {
        "slug": slug,
        "title": title,
        "short_title": short_title,
        "year": year,
        "act_number": act_number,
        "aliases": aliases,
        "coverage": "partial",
        "text_kind": "summary",
        "source": "curated summary - authentic text at the India Code URL",
        "india_code_url": url,
        "note": note,
        "sections": sections,
    }


def s(
    number: str, heading: str, text: str, chapter: str | None = None
) -> Dict[str, Any]:
    """One curated section entry."""
    return {"number": number, "heading": heading, "text": text, "chapter": chapter}


ACTS: List[Dict[str, Any]] = [
    act(
        slug="indian-contract-act-1872",
        title="Indian Contract Act, 1872",
        short_title="Contract Act",
        year=1872,
        act_number="9 of 1872",
        aliases=["contract act", "ica", "indian contract act"],
        url="https://www.indiacode.nic.in/handle/123456789/2187",
        sections=[
            s(
                "10",
                "What agreements are contracts",
                "An agreement is a contract if made by the free consent of parties "
                "competent to contract, for a lawful consideration and with a lawful "
                "object, and not expressly declared void.",
            ),
            s(
                "11",
                "Who are competent to contract",
                "Every person of the age of majority, of sound mind, and not "
                "disqualified by law is competent to contract. A minor's agreement is "
                "void ab initio.",
            ),
            s(
                "16",
                "Undue influence",
                "A contract is induced by undue influence where one party is in a "
                "position to dominate the will of the other and uses that position to "
                "obtain an unfair advantage. Where undue influence is shown, the burden "
                "of proving the contract was not so induced lies on the dominant party.",
            ),
            s(
                "17",
                "Fraud",
                "Fraud includes suggesting as a fact what is not true by one who does "
                "not believe it true, active concealment, a promise made without "
                "intention of performing it, and any other act fitted to deceive. Mere "
                "silence is not fraud unless there is a duty to speak.",
            ),
            s(
                "23",
                "What considerations and objects are lawful",
                "Consideration or object is unlawful if forbidden by law, if it would "
                "defeat the provisions of any law, is fraudulent, involves injury to "
                "person or property, or is immoral or opposed to public policy. An "
                "agreement with unlawful consideration or object is void.",
            ),
            s(
                "27",
                "Agreement in restraint of trade, void",
                "Every agreement by which anyone is restrained from exercising a lawful "
                "profession, trade or business is to that extent void, subject only to "
                "the statutory exception for the sale of goodwill. Indian law does not "
                "apply the English 'reasonableness' test: a post-termination restraint "
                "on an employee is generally void, while a restraint operating during "
                "the term of employment may be upheld.",
            ),
            s(
                "28",
                "Agreements in restraint of legal proceedings, void",
                "An agreement that absolutely restricts a party from enforcing rights "
                "through the ordinary tribunals, or that limits the time within which "
                "rights may be enforced, is void. An exclusive-jurisdiction clause "
                "choosing between two courts that both otherwise have jurisdiction does "
                "not offend this section.",
            ),
            s(
                "56",
                "Agreement to do impossible act - frustration",
                "A contract to do an act which after it is made becomes impossible, or "
                "unlawful by an event the promisor could not prevent, becomes void when "
                "the act becomes impossible or unlawful. Commercial hardship or "
                "onerousness alone does not frustrate a contract.",
            ),
            s(
                "73",
                "Compensation for loss caused by breach of contract",
                "The party suffering breach is entitled to compensation for loss "
                "naturally arising in the usual course of things from the breach, or "
                "which the parties knew when contracting would be likely to result. "
                "Remote and indirect loss is not compensable. The claimant must mitigate.",
            ),
            s(
                "74",
                "Compensation for breach where penalty is stipulated",
                "Where a sum is named in the contract as payable on breach, the party "
                "complaining is entitled to reasonable compensation not exceeding that "
                "sum, whether or not actual damage is proved. Indian law does not "
                "distinguish liquidated damages from penalties in the English manner; "
                "the ceiling is the named sum and the measure is reasonableness.",
            ),
        ],
    ),
    act(
        slug="limitation-act-1963",
        title="Limitation Act, 1963",
        short_title="Limitation Act",
        year=1963,
        act_number="36 of 1963",
        aliases=["limitation act"],
        url="https://www.indiacode.nic.in/handle/123456789/1595",
        note="The Schedule of limitation periods is modelled separately in "
        "legal_mcp_server/src/domain/limitation.py.",
        sections=[
            s(
                "3",
                "Bar of limitation",
                "A suit, appeal or application filed after the prescribed period must be "
                "dismissed even if limitation is not pleaded as a defence. The court is "
                "bound to apply it of its own motion.",
            ),
            s(
                "4",
                "Expiry of prescribed period when court is closed",
                "Where the prescribed period expires on a day the court is closed, the "
                "proceeding may be instituted on the next day the court reopens.",
            ),
            s(
                "5",
                "Extension of prescribed period in certain cases",
                "An appeal or application (not a suit) may be admitted after the "
                "prescribed period if the applicant satisfies the court of sufficient "
                "cause for the delay. Section 5 does not apply to suits.",
            ),
            s(
                "12",
                "Exclusion of time in legal proceedings",
                "In computing limitation, the day from which the period runs is "
                "excluded. For an appeal or revision, the time taken to obtain a copy of "
                "the decree, order or judgment appealed from is also excluded.",
            ),
            s(
                "14",
                "Exclusion of time of proceeding bona fide in court without jurisdiction",
                "Time spent prosecuting another civil proceeding with due diligence and "
                "in good faith, against the same party and for the same relief, is "
                "excluded where that proceeding failed for defect of jurisdiction or "
                "other cause of a like nature.",
            ),
            s(
                "17",
                "Effect of fraud or mistake",
                "Where the suit is based on fraud, or the right of action is concealed "
                "by fraud, or relief is sought from the consequences of a mistake, "
                "limitation runs from when the plaintiff discovered the fraud or "
                "mistake, or could with reasonable diligence have discovered it.",
            ),
            s(
                "18",
                "Effect of acknowledgment in writing",
                "A fresh period of limitation runs from the date of a signed written "
                "acknowledgment of liability, provided it is made before the original "
                "period expires. An acknowledgment after expiry does not revive a "
                "time-barred claim.",
            ),
            s(
                "19",
                "Effect of payment on account of debt or of interest on legacy",
                "Where part payment of a debt, or payment of interest, is made before "
                "expiry of the period, a fresh period runs from the date of payment, "
                "provided the payment is acknowledged in the payer's handwriting or in a "
                "signed writing.",
            ),
        ],
    ),
    act(
        slug="consumer-protection-act-2019",
        title="Consumer Protection Act, 2019",
        short_title="CPA 2019",
        year=2019,
        act_number="35 of 2019",
        aliases=["cpa", "consumer protection act", "consumer act"],
        url="https://www.indiacode.nic.in/handle/123456789/15256",
        sections=[
            s(
                "2(7)",
                "Definition of consumer",
                "A person who buys goods or hires services for consideration, including "
                "a user with the buyer's approval, but excluding a person who obtains "
                "goods for resale or services for a commercial purpose. Goods or "
                "services obtained exclusively for earning a livelihood by self-"
                "employment are not a commercial purpose.",
            ),
            s(
                "2(11)",
                "Definition of deficiency",
                "Any fault, imperfection, shortcoming or inadequacy in the quality, "
                "nature or manner of performance of a service required to be maintained "
                "by law or undertaken by contract, including any act of negligence or "
                "withholding of relevant information.",
            ),
            s(
                "34",
                "Jurisdiction of District Commission",
                "The District Commission entertains complaints where the value of the "
                "goods or services paid as consideration does not exceed the prescribed "
                "pecuniary limit. A complaint may be filed where the opposite party "
                "resides or carries on business, where the cause of action arose, or "
                "where the complainant resides or personally works for gain.",
            ),
            s(
                "35",
                "Manner in which complaint shall be made",
                "A complaint may be filed by the consumer, a recognised consumer "
                "association, one or more consumers with the same interest, the Central "
                "or a State Government, or the Central Authority. Complaints may be "
                "filed electronically.",
            ),
            s(
                "38",
                "Procedure on admission of complaint",
                "The Commission refers a copy to the opposite party, which must respond "
                "within thirty days, extendable by up to fifteen days. Complaints are to "
                "be decided within three months, or five months where analysis or "
                "testing of goods is required.",
            ),
            s(
                "69",
                "Limitation period",
                "A complaint must be filed within two years from the date on which the "
                "cause of action arose. A complaint may be entertained after that period "
                "if the complainant satisfies the Commission of sufficient cause, with "
                "reasons recorded.",
            ),
        ],
    ),
    act(
        slug="bharatiya-nyaya-sanhita-2023",
        title="Bharatiya Nyaya Sanhita, 2023",
        short_title="BNS",
        year=2023,
        act_number="45 of 2023",
        aliases=["bns", "nyaya sanhita", "bharatiya nyaya sanhita"],
        url="https://www.indiacode.nic.in/handle/123456789/20062",
        note="In force from 1 July 2024. Replaced the Indian Penal Code, 1860. "
        "Applies to offences committed on or after that date.",
        sections=[
            s(
                "101",
                "Murder",
                "Culpable homicide amounting to murder. Corresponds to "
                "section 300 IPC; punishment provisions follow.",
            ),
            s(
                "103",
                "Punishment for murder",
                "Death or imprisonment for life, and fine. Corresponds to section 302 IPC.",
            ),
            s(
                "105",
                "Punishment for culpable homicide not amounting to murder",
                "Corresponds to section 304 IPC.",
            ),
            s(
                "115",
                "Voluntarily causing hurt",
                "Corresponds to sections 321 and 323 IPC.",
            ),
            s(
                "117",
                "Voluntarily causing grievous hurt",
                "Corresponds to sections 322 and 325 IPC.",
            ),
            s(
                "124",
                "Causing grievous hurt by acid attack",
                "Corresponds to section 326A IPC.",
            ),
            s("303", "Theft", "Corresponds to sections 378 and 379 IPC."),
            s("308", "Extortion", "Corresponds to sections 383 and 384 IPC."),
            s(
                "316",
                "Criminal breach of trust",
                "Corresponds to sections 405 and 406 IPC.",
            ),
            s(
                "318",
                "Cheating and dishonestly inducing delivery of property",
                "Corresponds to sections 415, 417 and 420 IPC.",
            ),
            s("324", "Mischief", "Corresponds to sections 425 and 426 IPC."),
            s(
                "329",
                "Criminal trespass and house-trespass",
                "Corresponds to sections 441 and 442 IPC.",
            ),
            s(
                "351",
                "Criminal intimidation",
                "Corresponds to sections 503 and 506 IPC.",
            ),
            s("356", "Defamation", "Corresponds to sections 499 and 500 IPC."),
            s("63", "Rape", "Corresponds to section 375 IPC."),
            s("64", "Punishment for rape", "Corresponds to section 376 IPC."),
            s(
                "85",
                "Cruelty to a married woman by husband or his relatives",
                "Corresponds to section 498A IPC.",
            ),
            s(
                "111",
                "Organised crime",
                "A new offence with no direct IPC equivalent, covering continuing "
                "unlawful activity by organised crime syndicates.",
            ),
            s("113", "Terrorist act", "A new offence with no direct IPC equivalent."),
        ],
    ),
    act(
        slug="bharatiya-nagarik-suraksha-sanhita-2023",
        title="Bharatiya Nagarik Suraksha Sanhita, 2023",
        short_title="BNSS",
        year=2023,
        act_number="46 of 2023",
        aliases=["bnss", "nagarik suraksha sanhita"],
        url="https://www.indiacode.nic.in/handle/123456789/20063",
        note="In force from 1 July 2024. Replaced the Code of Criminal Procedure, 1973.",
        sections=[
            s(
                "173",
                "Information in cognizable cases",
                "Registration of a First Information Report, including zero FIR and "
                "electronic registration. Corresponds to section 154 CrPC.",
            ),
            s(
                "175",
                "Police officer's power to investigate cognizable case",
                "Corresponds to section 156 CrPC, including the magistrate's power to "
                "order investigation.",
            ),
            s(
                "187",
                "Procedure when investigation cannot be completed in 24 hours",
                "Remand provisions. Corresponds to section 167 CrPC.",
            ),
            s(
                "193",
                "Report of police officer on completion of investigation",
                "The charge-sheet. Corresponds to section 173 CrPC.",
            ),
            s(
                "223",
                "Examination of complainant",
                "Corresponds to section 200 CrPC; adds a mandatory hearing for the "
                "accused before cognizance on a complaint.",
            ),
            s("262", "Discharge", "Corresponds to section 227 CrPC."),
            s("478", "Bail in bailable offences", "Corresponds to section 436 CrPC."),
            s(
                "479",
                "Maximum period of detention of undertrial prisoner",
                "Corresponds to section 436A CrPC, with a stricter regime for "
                "first-time offenders.",
            ),
            s(
                "480",
                "Bail in non-bailable offences",
                "Corresponds to section 437 CrPC.",
            ),
            s(
                "482",
                "Anticipatory bail",
                "Direction for release on bail to a person apprehending arrest. "
                "Corresponds to section 438 CrPC.",
            ),
            s(
                "528",
                "Inherent powers of the High Court",
                "Corresponds to section 482 CrPC - the quashing jurisdiction.",
            ),
        ],
    ),
    act(
        slug="bharatiya-sakshya-adhiniyam-2023",
        title="Bharatiya Sakshya Adhiniyam, 2023",
        short_title="BSA",
        year=2023,
        act_number="47 of 2023",
        aliases=["bsa", "sakshya adhiniyam"],
        url="https://www.indiacode.nic.in/handle/123456789/20064",
        note="In force from 1 July 2024. Replaced the Indian Evidence Act, 1872.",
        sections=[
            s(
                "3",
                "Evidence may be given of facts in issue and relevant facts",
                "Corresponds to section 5 of the Evidence Act.",
            ),
            s(
                "24",
                "Admission defined",
                "Corresponds to section 17 of the Evidence Act.",
            ),
            s(
                "39",
                "Opinion of experts",
                "Corresponds to section 45 of the Evidence Act.",
            ),
            s(
                "57",
                "Primary evidence",
                "Corresponds to section 62 of the Evidence Act.",
            ),
            s(
                "58",
                "Secondary evidence",
                "Corresponds to section 63 of the Evidence Act.",
            ),
            s(
                "61",
                "Electronic or digital record",
                "Electronic records are not to be denied admissibility solely on the "
                "ground of being electronic. No direct Evidence Act equivalent.",
            ),
            s(
                "63",
                "Admissibility of electronic records",
                "Conditions for admitting computer output, with a certificate "
                "requirement. Corresponds to section 65B of the Evidence Act.",
            ),
            s(
                "104",
                "Burden of proof",
                "Corresponds to section 101 of the Evidence Act.",
            ),
            s(
                "119",
                "Presumption as to abetment of suicide by a married woman",
                "Corresponds to section 113A of the Evidence Act.",
            ),
        ],
    ),
    act(
        slug="constitution-of-india",
        title="Constitution of India",
        short_title="Constitution",
        year=1950,
        act_number="-",
        aliases=["constitution", "constitution of india", "coi"],
        url="https://www.indiacode.nic.in/handle/123456789/15240",
        note="Entries are Articles, not sections.",
        sections=[
            s(
                "14",
                "Equality before law",
                "The State shall not deny to any person equality before the law or the "
                "equal protection of the laws within the territory of India.",
            ),
            s(
                "19",
                "Protection of certain rights regarding freedom of speech etc.",
                "Guarantees to citizens freedom of speech and expression, assembly, "
                "association, movement, residence, and profession, each subject to "
                "reasonable restrictions on the grounds specified in the Article.",
            ),
            s(
                "20",
                "Protection in respect of conviction for offences",
                "No ex post facto criminal liability, no double jeopardy, and no "
                "compulsion to be a witness against oneself.",
            ),
            s(
                "21",
                "Protection of life and personal liberty",
                "No person shall be deprived of life or personal liberty except "
                "according to procedure established by law - read to require that the "
                "procedure be fair, just and reasonable.",
            ),
            s(
                "22",
                "Protection against arrest and detention in certain cases",
                "Grounds of arrest to be communicated, right to consult a legal "
                "practitioner, and production before a magistrate within 24 hours.",
            ),
            s(
                "32",
                "Remedies for enforcement of fundamental rights",
                "The right to move the Supreme Court by appropriate proceedings for the "
                "enforcement of fundamental rights. Itself a fundamental right.",
            ),
            s(
                "226",
                "Power of High Courts to issue certain writs",
                "Every High Court may issue writs for the enforcement of fundamental "
                "rights and for any other purpose, throughout its territorial "
                "jurisdiction. Wider than Article 32.",
            ),
            s(
                "227",
                "Power of superintendence over all courts by the High Court",
                "Supervisory jurisdiction over all courts and tribunals within the "
                "High Court's territories.",
            ),
            s(
                "300A",
                "Persons not to be deprived of property save by authority of law",
                "No person shall be deprived of property save by authority of law. A "
                "constitutional right, not a fundamental right.",
            ),
        ],
    ),
    act(
        slug="arbitration-and-conciliation-act-1996",
        title="Arbitration and Conciliation Act, 1996",
        short_title="Arbitration Act",
        year=1996,
        act_number="26 of 1996",
        aliases=["arbitration act", "a&c act", "arbitration and conciliation act"],
        url="https://www.indiacode.nic.in/handle/123456789/1978",
        sections=[
            s(
                "7",
                "Arbitration agreement",
                "An agreement to submit present or future disputes to arbitration. It "
                "must be in writing, which includes an exchange of communications or "
                "pleadings in which existence is alleged and not denied.",
            ),
            s(
                "8",
                "Power to refer parties to arbitration",
                "A judicial authority before which an action is brought in a matter "
                "covered by an arbitration agreement shall refer the parties to "
                "arbitration unless it finds prima facie that no valid agreement exists.",
            ),
            s(
                "9",
                "Interim measures by court",
                "A party may apply to court for interim measures before or during "
                "arbitral proceedings, or after the award but before enforcement.",
            ),
            s(
                "11",
                "Appointment of arbitrators",
                "Where parties fail to appoint under the agreed procedure, the Supreme "
                "Court or High Court, or a person or institution designated by it, makes "
                "the appointment, confining itself to the existence of the agreement.",
            ),
            s(
                "16",
                "Competence of arbitral tribunal to rule on its jurisdiction",
                "The kompetenz-kompetenz principle: the tribunal may rule on its own "
                "jurisdiction, including on the existence or validity of the arbitration "
                "agreement, which is treated as separable from the main contract.",
            ),
            s(
                "21",
                "Commencement of arbitral proceedings",
                "Unless otherwise agreed, proceedings commence on the date the request "
                "to refer the dispute to arbitration is received by the respondent. "
                "Relevant to limitation.",
            ),
            s(
                "29A",
                "Time limit for arbitral award",
                "The award in a domestic arbitration is to be made within twelve months "
                "from completion of pleadings, extendable by six months by consent and "
                "thereafter only by the court.",
            ),
            s(
                "34",
                "Application for setting aside arbitral award",
                "The only recourse against an award. Grounds are narrow: incapacity, "
                "invalid agreement, want of notice, matters beyond the scope of "
                "submission, irregular composition, non-arbitrability, or conflict with "
                "the public policy of India. Must be filed within three months, "
                "extendable by thirty days on sufficient cause and no further.",
            ),
            s(
                "37",
                "Appealable orders",
                "Appeals lie from orders refusing to refer to arbitration, granting or "
                "refusing interim measures, and setting aside or refusing to set aside "
                "an award.",
            ),
        ],
    ),
    act(
        slug="specific-relief-act-1963",
        title="Specific Relief Act, 1963",
        short_title="SRA",
        year=1963,
        act_number="47 of 1963",
        aliases=["specific relief act", "sra"],
        url="https://www.indiacode.nic.in/handle/123456789/1583",
        sections=[
            s(
                "10",
                "Specific performance of contract",
                "Specific performance shall be enforced by the court subject to the "
                "limits in sections 11(2), 14 and 16. Since the 2018 amendment it is a "
                "general rule rather than a discretionary remedy.",
            ),
            s(
                "14",
                "Contracts not specifically enforceable",
                "Includes contracts where a party has obtained substituted performance, "
                "those involving continuous duty the court cannot supervise, those "
                "dependent on personal qualifications, and those determinable in nature.",
            ),
            s(
                "16",
                "Personal bars to relief",
                "Specific performance is not to be granted to one who has obtained "
                "substituted performance, is incapable of performing, or fails to prove "
                "readiness and willingness to perform their part throughout.",
            ),
            s(
                "20A",
                "No injunction in infrastructure project contracts",
                "Courts shall not grant an injunction where it would cause impediment or "
                "delay in the progress of a notified infrastructure project.",
            ),
            s(
                "34",
                "Discretion of court as to declaration of status or right",
                "A person entitled to a legal character or right to property may sue for "
                "a declaration; but no declaration shall be made where the plaintiff, "
                "being able to seek further relief, omits to do so.",
            ),
            s(
                "38",
                "Perpetual injunction when granted",
                "A perpetual injunction may be granted to prevent breach of an "
                "obligation existing in the plaintiff's favour, including where the "
                "defendant invades or threatens to invade the plaintiff's right to "
                "enjoyment of property.",
            ),
            s(
                "41",
                "Injunction when refused",
                "Lists the cases in which an injunction cannot be granted, including to "
                "restrain proceedings in a court not subordinate to that from which the "
                "injunction is sought, and where equally efficacious relief is available.",
            ),
        ],
    ),
    act(
        slug="information-technology-act-2000",
        title="Information Technology Act, 2000",
        short_title="IT Act",
        year=2000,
        act_number="21 of 2000",
        aliases=["it act", "information technology act", "ita"],
        url="https://www.indiacode.nic.in/handle/123456789/1999",
        sections=[
            s(
                "43",
                "Penalty and compensation for damage to computer system",
                "Civil liability for unauthorised access, downloading, introduction of "
                "contaminants, damage, disruption, denial of access or tampering.",
            ),
            s(
                "43A",
                "Compensation for failure to protect data",
                "A body corporate handling sensitive personal data that is negligent in "
                "maintaining reasonable security practices is liable to pay compensation.",
            ),
            s(
                "65",
                "Tampering with computer source documents",
                "Knowingly concealing, destroying or altering computer source code "
                "required to be kept by law.",
            ),
            s(
                "66",
                "Computer related offences",
                "Dishonestly or fraudulently doing any act referred to in section 43.",
            ),
            s(
                "66C",
                "Punishment for identity theft",
                "Fraudulent or dishonest use of another person's electronic signature, "
                "password or other unique identification feature.",
            ),
            s(
                "66D",
                "Punishment for cheating by personation using a computer resource",
                "Cheating by personation by means of any communication device or "
                "computer resource - the provision used for most online fraud.",
            ),
            s(
                "66E",
                "Punishment for violation of privacy",
                "Intentionally capturing, publishing or transmitting the image of a "
                "private area of any person without consent.",
            ),
            s(
                "67",
                "Punishment for publishing obscene material in electronic form",
                "Publishing or transmitting obscene material in electronic form.",
            ),
            s(
                "69A",
                "Power to issue directions for blocking public access",
                "The Central Government may direct blocking of information in the "
                "interest of sovereignty, security, public order and related grounds, "
                "following the prescribed procedure.",
            ),
            s(
                "79",
                "Exemption from liability of intermediary",
                "Safe harbour for intermediaries that only provide access and do not "
                "initiate, select the receiver of, or modify the transmission, subject "
                "to observing due diligence and acting on actual knowledge.",
            ),
        ],
    ),
    act(
        slug="transfer-of-property-act-1882",
        title="Transfer of Property Act, 1882",
        short_title="TP Act",
        year=1882,
        act_number="4 of 1882",
        aliases=["tpa", "tp act", "transfer of property act"],
        url="https://www.indiacode.nic.in/handle/123456789/2338",
        sections=[
            s(
                "53A",
                "Part performance",
                "Where a transferee in part performance of a written contract for "
                "transfer of immovable property has taken possession and is willing to "
                "perform, the transferor is barred from enforcing rights against the "
                "transferee other than those expressly provided by the contract. A "
                "shield, not a sword, and the contract must be registered.",
            ),
            s(
                "54",
                "Sale defined",
                "Transfer of ownership in exchange for a price. Sale of tangible "
                "immovable property of value one hundred rupees and upwards can be made "
                "only by a registered instrument.",
            ),
            s(
                "105",
                "Lease defined",
                "A transfer of a right to enjoy immovable property for a term or in "
                "perpetuity, in consideration of a price or rent.",
            ),
            s(
                "106",
                "Duration of certain leases in absence of written contract",
                "A lease of immovable property for agricultural or manufacturing "
                "purposes is deemed year to year, terminable on six months' notice; any "
                "other lease is deemed month to month, terminable on fifteen days' notice.",
            ),
            s(
                "107",
                "Leases how made",
                "A lease from year to year, or for a term exceeding one year, or "
                "reserving a yearly rent, can be made only by a registered instrument.",
            ),
            s(
                "108",
                "Rights and liabilities of lessor and lessee",
                "Sets out the default obligations of landlord and tenant in the absence "
                "of contract or local usage to the contrary.",
            ),
            s(
                "111",
                "Determination of lease",
                "The ways a lease comes to an end: efflux of time, happening of a "
                "specified event, merger, surrender, forfeiture and notice to quit.",
            ),
        ],
    ),
    act(
        slug="right-to-information-act-2005",
        title="Right to Information Act, 2005",
        short_title="RTI Act",
        year=2005,
        act_number="22 of 2005",
        aliases=["rti act", "rti", "right to information act"],
        url="https://www.indiacode.nic.in/handle/123456789/2029",
        sections=[
            s(
                "6",
                "Request for obtaining information",
                "An application in writing or electronically, with the prescribed fee, "
                "to the Public Information Officer. The applicant is not required to "
                "give reasons for the request or any personal details beyond those "
                "necessary for contact.",
            ),
            s(
                "7",
                "Disposal of request",
                "The PIO must decide within thirty days of receipt, or within forty-"
                "eight hours where the information concerns life or liberty. Failure to "
                "decide within the period is deemed a refusal.",
            ),
            s(
                "8",
                "Exemption from disclosure of information",
                "Lists the exempt categories, including sovereignty and security, "
                "information forbidden by a court, commercial confidence, fiduciary "
                "relationship, and personal information with no public interest. Subject "
                "to the public interest override in the proviso.",
            ),
            s(
                "19",
                "Appeal",
                "A first appeal lies to the officer senior to the PIO within thirty days "
                "of the decision or the expiry of the response period. A second appeal "
                "lies to the Information Commission within ninety days.",
            ),
            s(
                "20",
                "Penalties",
                "The Information Commission may impose a penalty of two hundred and "
                "fifty rupees per day, up to twenty-five thousand rupees, on a PIO who "
                "refuses to receive an application or does not furnish information "
                "within time without reasonable cause.",
            ),
        ],
    ),
]


def main() -> int:
    """Write every curated Act file."""
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    for entry in ACTS:
        target = SEED_DIR / f"{entry['slug']}.json"
        target.write_text(
            json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"wrote {len(entry['sections']):>3} sections -> {target.name}")
    print(f"\n{len(ACTS)} curated Acts written to {SEED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
