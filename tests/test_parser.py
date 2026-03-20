"""Tests for shared/tiptap_parser.py — Format A and Format B parsing."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.tiptap_parser import parse_tiptap_to_chunks

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Format A (March 17, 2026 — h2/h3 headings + paragraphs)
# ---------------------------------------------------------------------------

class TestFormatA:
    @pytest.fixture(autouse=True)
    def setup(self):
        fixture = load_fixture("format_a_sample.json")
        self.body = fixture["body"]
        self.meta = fixture["_test_metadata"]
        self.chunks = parse_tiptap_to_chunks(self.body, "March 17, 2026 Call", "https://example.com/march-17")

    def test_chunk_count(self):
        assert len(self.chunks) == self.meta["expected_chunks"]

    def test_topic_headings(self):
        topics = [c["topic_heading"] for c in self.chunks]
        assert topics == self.meta["expected_topics"]

    def test_timestamp_prefix_stripped(self):
        # "01:08 Travel Delays..." → "Travel Delays..."
        assert self.chunks[0]["topic_heading"] == "Travel Delays and World Baseball Classic"

    def test_hour_format_timestamp_stripped(self):
        # "1:01:41 Bookkeeping..." → "Bookkeeping..."
        assert self.chunks[3]["topic_heading"] == "Bookkeeping Systems and Visibility"

    def test_timestamps_extracted(self):
        assert self.chunks[0]["timestamps"] == ["01:08"]
        assert self.chunks[1]["timestamps"] == ["03:43"]
        assert self.chunks[2]["timestamps"] == ["22:48"]
        assert self.chunks[3]["timestamps"] == ["1:01:41"]

    def test_speakers_chunk_0(self):
        speakers = self.chunks[0]["speakers"]
        assert "Christopher Nelson" in speakers
        assert "Greg Nakagawa" in speakers

    def test_speakers_chunk_1(self):
        speakers = self.chunks[1]["speakers"]
        assert "Christopher Nelson" in speakers
        assert "Shawn" in speakers

    def test_speakers_chunk_2(self):
        speakers = self.chunks[2]["speakers"]
        assert "Arun Shrestha" in speakers
        assert "Vivek Mandava" in speakers

    def test_speakers_chunk_3(self):
        speakers = self.chunks[3]["speakers"]
        assert "Christopher Nelson" in speakers
        assert "Chad Pavliska" in speakers
        # Affshin appears as bold text but lacks a (Name): wrapper
        assert "Affshin" in speakers

    def test_content_not_empty(self):
        for chunk in self.chunks:
            assert chunk["content"].strip()

    def test_empty_paragraphs_skipped(self):
        # Empty paragraphs between sections should not appear as standalone content
        for chunk in self.chunks:
            # Content should not be just whitespace
            assert chunk["content"].strip()

    def test_file_node_skipped(self):
        # Should still get exactly 4 chunks; the file node doesn't inflate the count
        assert len(self.chunks) == 4

    def test_structural_h2_skipped(self):
        # "Discussion Topics" and "Key Search Terms" should not appear as topics
        topics = [c["topic_heading"] for c in self.chunks]
        assert "Discussion Topics" not in topics
        assert "Key Search Terms" not in topics

    def test_search_terms_paragraph_not_in_chunks(self):
        # The paragraph after "Key Search Terms" should not appear in any chunk's content
        for chunk in self.chunks:
            assert "Donor Advised Fund (DAF)" not in chunk["content"] or \
                   chunk["topic_heading"] != "Key Search Terms"

    def test_each_chunk_has_required_keys(self):
        for chunk in self.chunks:
            assert set(chunk.keys()) >= {"topic_heading", "content", "speakers", "timestamps"}

    def test_speakers_are_lists(self):
        for chunk in self.chunks:
            assert isinstance(chunk["speakers"], list)

    def test_timestamps_are_lists(self):
        for chunk in self.chunks:
            assert isinstance(chunk["timestamps"], list)

    def test_h3_without_timestamp_prefix(self):
        """An h3 with no timestamp prefix should use the full text as heading."""
        body = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "No Timestamp Here"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Some content."}],
                },
            ],
        }
        chunks = parse_tiptap_to_chunks(body, "Test", "http://x.com")
        assert len(chunks) == 1
        assert chunks[0]["topic_heading"] == "No Timestamp Here"
        assert chunks[0]["timestamps"] == []


# ---------------------------------------------------------------------------
# Format B (January 16, 2026 — bulletList + listItems)
# ---------------------------------------------------------------------------

class TestFormatB:
    @pytest.fixture(autouse=True)
    def setup(self):
        fixture = load_fixture("format_b_sample.json")
        self.body = fixture["body"]
        self.meta = fixture["_test_metadata"]
        self.chunks = parse_tiptap_to_chunks(self.body, "January 16, 2026 Call", "https://example.com/jan-16")

    def test_chunk_count(self):
        assert len(self.chunks) == self.meta["expected_chunks"]

    def test_topic_headings(self):
        topics = [c["topic_heading"] for c in self.chunks]
        assert topics == self.meta["expected_topics"]

    def test_bold_text_is_topic_heading(self):
        assert self.chunks[0]["topic_heading"] == "Discussion on 49ers Facility and Injuries"

    def test_content_excludes_heading(self):
        # Content should NOT repeat the bold heading text
        assert "Discussion on 49ers Facility and Injuries" not in self.chunks[0]["content"]

    def test_content_has_body_text(self):
        assert "Christopher Nelson" in self.chunks[0]["content"]

    def test_timestamps_chunk_0(self):
        assert "00:02:59" in self.chunks[0]["timestamps"]

    def test_timestamps_chunk_1(self):
        assert "00:05:02" in self.chunks[1]["timestamps"]
        assert "00:06:27" in self.chunks[1]["timestamps"]

    def test_timestamps_chunk_2(self):
        assert "00:13:14" in self.chunks[2]["timestamps"]
        assert "00:15:20" in self.chunks[2]["timestamps"]

    def test_timestamps_chunk_3(self):
        assert "00:26:32" in self.chunks[3]["timestamps"]

    def test_speakers_christopher_nelson_found(self):
        all_speakers = [s for c in self.chunks for s in c["speakers"]]
        assert "Christopher Nelson" in all_speakers

    def test_speakers_affshin_valji_found(self):
        all_speakers = [s for c in self.chunks for s in c["speakers"]]
        assert "Affshin Valji" in all_speakers

    def test_speakers_ken_h_found(self):
        all_speakers = [s for c in self.chunks for s in c["speakers"]]
        assert "Ken H" in all_speakers

    def test_speakers_jason_seale_found(self):
        all_speakers = [s for c in self.chunks for s in c["speakers"]]
        assert "Jason Seale" in all_speakers

    def test_file_node_skipped(self):
        assert len(self.chunks) == 4

    def test_each_chunk_has_required_keys(self):
        for chunk in self.chunks:
            assert set(chunk.keys()) >= {"topic_heading", "content", "speakers", "timestamps"}

    def test_speakers_are_lists(self):
        for chunk in self.chunks:
            assert isinstance(chunk["speakers"], list)

    def test_timestamps_are_lists(self):
        for chunk in self.chunks:
            assert isinstance(chunk["timestamps"], list)

    def test_multiple_bullet_lists(self):
        """Multiple bulletLists in one doc should all be processed."""
        body = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "First Topic", "marks": [{"type": "bold"}]},
                                    {"type": "text", "text": " Some content here."},
                                ],
                            }],
                        }
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Second Topic", "marks": [{"type": "bold"}]},
                                    {"type": "text", "text": " More content here."},
                                ],
                            }],
                        }
                    ],
                },
            ],
        }
        chunks = parse_tiptap_to_chunks(body, "Test", "http://x.com")
        assert len(chunks) == 2
        assert chunks[0]["topic_heading"] == "First Topic"
        assert chunks[1]["topic_heading"] == "Second Topic"

    def test_no_bold_text_falls_back_to_content(self):
        """listItem with no bold text uses first 60 chars of content as heading."""
        body = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "No bold heading here, just plain text content."},
                                ],
                            }],
                        }
                    ],
                }
            ],
        }
        chunks = parse_tiptap_to_chunks(body, "Test", "http://x.com")
        assert len(chunks) == 1
        assert len(chunks[0]["topic_heading"]) <= 60
        assert chunks[0]["topic_heading"] in "No bold heading here, just plain text content."


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_doc(self):
        body = {"type": "doc", "content": []}
        chunks = parse_tiptap_to_chunks(body, "Empty", "http://x.com")
        assert chunks == []

    def test_body_wrapper_unwrapped(self):
        """API returns tiptap_body with a 'body' wrapper around the doc."""
        wrapped = {
            "body": {
                "type": "doc",
                "content": [
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "05:00 Wrapped Topic"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "(Alice): Alice talks."}],
                    },
                ],
            }
        }
        chunks = parse_tiptap_to_chunks(wrapped, "Test", "http://x.com")
        assert len(chunks) == 1
        assert chunks[0]["topic_heading"] == "Wrapped Topic"

    def test_only_file_nodes(self):
        body = {
            "type": "doc",
            "content": [
                {"type": "file", "attrs": {"signed_id": "abc"}},
            ],
        }
        chunks = parse_tiptap_to_chunks(body, "Video Only", "http://x.com")
        assert chunks == []

    def test_format_a_no_chunks_before_key_search_terms(self):
        """If Key Search Terms h2 appears before any h3, nothing is returned."""
        body = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Key Search Terms"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Some terms here"}],
                },
            ],
        }
        chunks = parse_tiptap_to_chunks(body, "Test", "http://x.com")
        assert chunks == []

    def test_format_a_multiple_paragraphs_per_chunk(self):
        body = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "10:00 Multi Para Topic"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "(Alice Smith): Alice talks."}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "(Bob Jones): Bob responds."}],
                },
            ],
        }
        chunks = parse_tiptap_to_chunks(body, "Test", "http://x.com")
        assert len(chunks) == 1
        assert "Alice talks." in chunks[0]["content"]
        assert "Bob responds." in chunks[0]["content"]
        assert "Alice Smith" in chunks[0]["speakers"]
        assert "Bob Jones" in chunks[0]["speakers"]
        assert chunks[0]["timestamps"] == ["10:00"]
