"""Tests for Indian citation parsing and normalisation."""

from legal_mcp_server.src.domain import citations as cit


class TestCaseCitations:
    """Extraction of reported and neutral case citations."""

    def test_bracketed_year_scc(self):
        """(2014) 9 SCC 129 is recognised with volume and page."""
        found = cit.extract_case_citations("see (2014) 9 SCC 129 at para 20")
        assert len(found) == 1
        assert found[0].normalized == "(2014) 9 SCC 129"
        assert found[0].year == 2014
        assert found[0].reporter == "SCC"
        assert found[0].page == "129"

    def test_air_leading_reporter(self):
        """AIR 1973 SC 1461 is recognised."""
        found = cit.extract_case_citations("AIR 1973 SC 1461")
        assert found[0].normalized == "AIR 1973 SC 1461"
        assert found[0].reporter == "AIR"

    def test_scc_online_year_first(self):
        """2021 SCC OnLine Bom 123 is recognised despite the year leading."""
        found = cit.extract_case_citations("2021 SCC OnLine Bom 123")
        assert found[0].normalized == "2021 SCC OnLine Bom 123"

    def test_neutral_citation_colon_form(self):
        """2024:BHC-AS:12345 is recognised as a neutral citation."""
        found = cit.extract_case_citations("reported as 2024:BHC-AS:12345")
        assert found[0].normalized == "2024:BHC-AS:12345"

    def test_insc_neutral(self):
        """2023 INSC 456 is recognised."""
        found = cit.extract_case_citations("2023 INSC 456")
        assert found[0].normalized == "2023 INSC 456"

    def test_year_volume_reporter_form(self):
        """1997 (3) ALL MR 200 is recognised."""
        found = cit.extract_case_citations("1997 (3) ALL MR 200")
        assert found[0].normalized == "1997 (3) ALL MR 200"

    def test_case_name_captured(self):
        """Party names adjacent to a citation are attached to it."""
        text = "In Swastik Gases v. Indian Oil, (2013) 9 SCC 32, the Court held"
        found = cit.extract_case_citations(text)
        assert found[0].case_name == "Swastik Gases v. Indian Oil"

    def test_lead_in_word_stripped_from_case_name(self):
        """A narrative lead-in is not treated as part of the party name."""
        text = "See Dashrath Rathod v. State of Maharashtra, (2014) 9 SCC 129"
        found = cit.extract_case_citations(text)
        assert found[0].case_name is not None
        assert not found[0].case_name.lower().startswith("see ")

    def test_in_re_preserved(self):
        """'In re' is part of the case name and must survive trimming."""
        assert cit._trim_lead_ins("In re Vinay Chandra Mishra").startswith("In re")

    def test_deduplication(self):
        """The same citation twice yields one entry."""
        found = cit.extract_case_citations(
            "(2014) 9 SCC 129 and again (2014) 9 SCC 129"
        )
        assert len(found) == 1

    def test_prose_without_citations(self):
        """Ordinary prose yields nothing rather than a false positive."""
        assert cit.extract_case_citations("The parties met on 5 occasions.") == []


class TestStatutoryCitations:
    """Extraction of section, article and order/rule references."""

    def test_full_section_reference(self):
        """A full section reference expands to the canonical Act name."""
        found = cit.extract_statutory_citations(
            "Section 138 of the Negotiable Instruments Act, 1881"
        )
        assert found[0].section == "138"
        assert found[0].statute == "Negotiable Instruments Act, 1881"

    def test_abbreviated_statute_expanded(self):
        """'s. 420 IPC' expands to the full Act title."""
        found = cit.extract_statutory_citations("charged under s. 420 IPC")
        assert found[0].section == "420"
        assert found[0].statute == "Indian Penal Code, 1860"

    def test_subsection_retained(self):
        """A sub-section is kept in the section field."""
        found = cit.extract_statutory_citations(
            "Section 4(2) of the Limitation Act, 1963"
        )
        assert found[0].section == "4(2)"

    def test_article_recognised(self):
        """Constitutional articles are classified separately."""
        found = cit.extract_statutory_citations("Article 21 of the Constitution")
        assert found[0].kind is cit.CitationKind.CONSTITUTION
        assert found[0].statute == "Constitution of India"

    def test_order_rule_recognised(self):
        """Order and Rule references under the CPC are recognised."""
        found = cit.extract_statutory_citations("Order VII Rule 11 CPC")
        assert found[0].section == "Order VII Rule 11"
        assert found[0].statute == "Code of Civil Procedure, 1908"


class TestExtractAll:
    """Combined extraction and single-citation parsing."""

    def test_mixed_text_ordered_by_position(self):
        """Case and statutory citations come back in document order."""
        text = (
            "Under Section 138 of the Negotiable Instruments Act, 1881, and as "
            "held in (2014) 9 SCC 129, the complaint lies."
        )
        found = cit.extract_all(text)
        assert len(found) == 2
        assert found[0].kind is cit.CitationKind.STATUTE
        assert found[1].kind is cit.CitationKind.CASE

    def test_empty_text(self):
        """Empty input yields an empty list, not an error."""
        assert cit.extract_all("") == []

    def test_parse_single_citation(self):
        """A lone citation string parses to one Citation."""
        parsed = cit.parse_citation("(2019) 5 SCC 266")
        assert parsed is not None
        assert parsed.year == 2019

    def test_parse_unrecognised_returns_none(self):
        """A string that is not a citation returns None rather than guessing."""
        assert cit.parse_citation("some arbitrary words") is None

    def test_search_query_includes_case_name(self):
        """The lookup query combines party names with the citation."""
        text = "Swastik Gases v. Indian Oil, (2013) 9 SCC 32"
        query = cit.extract_case_citations(text)[0].search_query()
        assert "Swastik Gases" in query
        assert "(2013) 9 SCC 32" in query
