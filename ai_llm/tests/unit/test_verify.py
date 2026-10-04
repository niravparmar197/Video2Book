"""Unit tests for app.nodes.verify — judge score for a written section.

No real LLM calls: app.nodes.verify.call_writer is monkeypatched.
"""
import json

from app.nodes import verify as verify_node


def test_run_verify_parses_a_passing_score(monkeypatch):
    monkeypatch.setattr(
        verify_node,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 9, "feedback": "Great section."}),
    )

    result = verify_node.run_verify("transcript text", "notes text")

    assert result.score == 9
    assert result.feedback == "Great section."


def test_run_verify_parses_a_failing_score(monkeypatch):
    monkeypatch.setattr(
        verify_node,
        "call_writer",
        lambda prompt, **kw: json.dumps({"score": 4, "feedback": "Missing key facts."}),
    )

    result = verify_node.run_verify("transcript text", "notes text")

    assert result.score == 4
    assert result.feedback == "Missing key facts."


def test_run_verify_includes_transcript_and_notes_in_prompt(monkeypatch):
    captured = {}

    def fake_call_writer(prompt, **kw):
        captured["prompt"] = prompt
        return json.dumps({"score": 8, "feedback": "ok"})

    monkeypatch.setattr(verify_node, "call_writer", fake_call_writer)

    verify_node.run_verify("UNIQUE_TRANSCRIPT_TEXT", "UNIQUE_NOTES_TEXT")

    assert "UNIQUE_TRANSCRIPT_TEXT" in captured["prompt"]
    assert "UNIQUE_NOTES_TEXT" in captured["prompt"]


def test_run_verify_degrades_to_borderline_score_on_malformed_response(monkeypatch):
    monkeypatch.setattr(verify_node, "call_writer", lambda prompt, **kw: "I cannot comply.")

    result = verify_node.run_verify("transcript", "notes")

    assert result.score < 7  # below default PASS_SCORE, triggers a refine attempt
    assert result.feedback


def test_run_verify_extracts_json_from_surrounding_prose(monkeypatch):
    response = 'Here is my evaluation: {"score": 6, "feedback": "Decent but thin."} Hope that helps.'
    monkeypatch.setattr(verify_node, "call_writer", lambda prompt, **kw: response)

    result = verify_node.run_verify("transcript", "notes")

    assert result.score == 6
    assert result.feedback == "Decent but thin."


def test_run_verify_reasks_the_judge_once_before_falling_back_to_borderline(monkeypatch):
    responses = iter(["I think the notes are fine.", json.dumps({"score": 8, "feedback": "Good."})])
    prompts = []

    def fake_call_writer(prompt, **kw):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(verify_node, "call_writer", fake_call_writer)

    result = verify_node.run_verify("transcript text", "notes text")

    assert result.score == 8
    assert len(prompts) == 2
    assert "not the required JSON object" in prompts[1]


_CHART = '```chart\n{"type": "bar", "title": "T", "categories": ["UML", "Coding"], "values": [%s]}\n```'


def test_strip_ungrounded_visuals_drops_a_chart_with_a_value_the_speaker_never_said():
    transcript = "Spend only 10 15 minutes on the UML in a 45 minute round."
    notes = "## Time\nText.\n\n" + _CHART % "15, 30" + "\n\n## Next\nMore."

    cleaned = verify_node.strip_ungrounded_visuals(notes, transcript)

    assert "```chart" not in cleaned
    assert "## Time" in cleaned and "## Next" in cleaned


def test_strip_ungrounded_visuals_keeps_a_chart_whose_values_are_all_spoken():
    transcript = "Spend fifteen minutes on UML and 45 minutes in total."
    notes = "## Time\n" + _CHART % "15, 45"

    assert verify_node.strip_ungrounded_visuals(notes, transcript) == notes


def test_strip_ungrounded_visuals_leaves_unparseable_charts_for_render_to_handle():
    notes = "## Time\n```chart\n{not json\n```"

    assert verify_node.strip_ungrounded_visuals(notes, "15 minutes") == notes


def test_strip_ungrounded_visuals_drops_only_table_rows_with_unspoken_numbers():
    transcript = "Spend 10 15 minutes on UML."
    table = (
        '```table\n{"headers": ["Activity", "Minutes"], "rows": '
        '[["UML sketch", "10-15"], ["Coding", "25-35"]]}\n```'
    )

    cleaned = verify_node.strip_ungrounded_visuals("## T\n" + table, transcript)

    assert "UML sketch" in cleaned
    assert "Coding" not in cleaned


def test_strip_ungrounded_visuals_drops_a_table_when_every_row_is_ungrounded():
    table = '```table\n{"headers": ["A", "B"], "rows": [["x", "99"]]}\n```'

    assert "```table" not in verify_node.strip_ungrounded_visuals("## T\n" + table, "no numbers")


def test_strip_ungrounded_visuals_ignores_row_index_cells_and_text_only_tables():
    table = '```table\n{"headers": ["#", "Step"], "rows": [["1", "Begin"], ["2.", "Commit"]]}\n```'

    assert verify_node.strip_ungrounded_visuals("## T\n" + table, "no numbers") == "## T\n" + table


_SPOKEN = (
    "so a singleton pattern means only one object is created and a builder creates the "
    "object step by step like a parking lot for a car with a wheel and an engine "
    "and is a and has a link"
)


def test_find_unsupported_terms_flags_names_the_speaker_never_said():
    notes = (
        "## Patterns\n"
        "- **Singleton**: one shared object.\n"
        "- Others include *Observer*, *Strategy* and `Ticket` classes.\n"
        "- Also the Visitor idea.\n"
    )

    assert verify_node.find_unsupported_terms(notes, _SPOKEN) == [
        "observer",
        "strategy",
        "ticket",
        "visitor",
    ]


def test_find_unsupported_terms_ignores_spoken_words_analogies_hyphens_and_plurals():
    notes = (
        "## Patterns\n"
        "> Think of it like a *Kitchen* with a *Chef*.\n"
        "- **Singleton** and **Builders** use the Parking-Lot idea with a **Car**.\n"
        "- Is-a and Has-a links.\n"
        "- Sentence start is fine. Another one.\n"
    )

    assert verify_node.find_unsupported_terms(notes, _SPOKEN) == []


def test_remove_unsupported_terms_drops_lines_and_visual_blocks_but_keeps_headings():
    notes = (
        "## Observer pattern\n"
        "- **Observer** notifies.\n"
        "- **Singleton** is kept.\n"
        '```table\n{"headers": ["P"], "rows": [["Observer"]]}\n```\n'
        '```diagram\n{"nodes": ["Singleton", "Builder"], "edges": [["Singleton", "Builder"]]}\n```\n'
    )

    cleaned = verify_node.remove_unsupported_terms(notes, ["observer"])

    assert "## Observer pattern" in cleaned
    assert "notifies" not in cleaned
    assert "```table" not in cleaned
    assert "Singleton** is kept" in cleaned
    assert "```diagram" in cleaned


def test_clean_notes_drops_empty_callouts_and_source_meta_talk():
    notes = (
        "## T\n"
        "> **Watch out:** None\n"
        "> Watch out: No warnings given.\n"
        "> Example: Parking lot.\n"
        "- Behavioral (examples not explicitly named in source).\n"
        "- Flyweight (repeated in source).\n"
        "- Kept line.\n"
    )

    cleaned = verify_node.clean_notes(notes)

    assert cleaned == "## T\n> Example: Parking lot.\n- Kept line."


def test_find_unsupported_terms_splits_camel_case_and_skips_acronyms():
    transcript = "a two wheeler is a vehicle and so is a four wheeler, in high level design"
    notes = "- `TwoWheeler` and `FourWheeler` are vehicles.\n- **HLD** comes first, then *LLD*.\n"

    assert verify_node.find_unsupported_terms(notes, transcript) == []


def test_clean_notes_drops_stray_visual_headings_and_not_listed_meta():
    notes = "## T\n### Visual\n### Visual aid\n- Typical ones (not listed explicitly): x.\n- Kept.\n### Real heading\n"

    assert verify_node.clean_notes(notes) == "## T\n- Kept.\n### Real heading"


_HINDI = "नमस्ते दोस्तों आज हम रूस के इतिहास के बारे में बात करेंगे " * 20


def test_grounding_checks_are_skipped_for_a_non_english_transcript():
    notes = (
        "## Russia\n- *Moscow*, *Kremlin*, `Volga` and *Siberia* matter.\n"
        '```chart\n{"type": "bar", "title": "T", "categories": ["a"], "values": [1500]}\n```\n'
    )

    assert verify_node.find_unsupported_terms(notes, _HINDI) == []
    assert verify_node.strip_ungrounded_visuals(notes, _HINDI) == notes


def test_grounding_checks_still_run_for_an_english_transcript():
    notes = "## Russia\n- *Moscow*, *Kremlin*, `Volga` and *Siberia* matter.\n"

    # Moscow opens the bullet (treated as emphasis, not a name); the rest still count.
    assert verify_node.find_unsupported_terms(notes, "we talk about trade routes today") == [
        "kremlin",
        "volga",
        "siberia",
    ]


def test_find_unsupported_terms_ignores_emphasised_everyday_words_and_bolded_bullet_starts():
    # A real podcast book lost good lines because paraphrased emphasis words
    # ("effort", "pick", "rapid experiments") were treated as invented names.
    transcript = "hard work is a myth you have to choose the right problem and test fast at netflix"
    notes = (
        "## Focus\n"
        "- **Pick** one problem and put in **effort** with *rapid experiments*.\n"
        "- **Embrace Tactics** that work. Netflix tested fast.\n"
    )

    assert verify_node.find_unsupported_terms(notes, transcript) == []


def test_clean_notes_fixes_a_doubled_analogy_lead_and_drops_no_mention_asides():
    notes = (
        "## T\n"
        "> Think of it like: **Think of it like** a crowded hallway.\n"
        "- Result: people loved it (no mention of retention numbers).\n"
        "- Kept.\n"
    )

    assert verify_node.clean_notes(notes) == (
        "## T\n> Example: Think of it like a crowded hallway.\n- Kept."
    )


def test_clean_notes_moves_bullet_quotes_into_the_quote_box():
    notes = '## T\n- **Quote:** "People loved it."\n**Quote**: "They told their friends."\n- Kept.\n'

    assert verify_node.clean_notes(notes) == (
        '## T\n> Quote: "People loved it."\n> Quote: "They told their friends."\n- Kept.'
    )


def test_find_unsupported_terms_ignores_lowercase_technical_words_in_code_spans():
    # Real warnings from a 4-hour system-design book: 'graph', 'key', 'value',
    # 'runtime', 'typical', 'inspection', 'resource', 'identifier' were removed.
    notes = (
        "## Storage\n"
        "- A store maps a `key` to a `value` at `runtime`; a `resource identifier` is typical.\n"
        "- Classes like `Ticket` and `ParkingSpot` hold state.\n"
    )

    assert verify_node.find_unsupported_terms(notes, "we store data and look it up fast") == [
        "ticket",
        "parking",
        "spot",
    ]


def test_judge_reply_with_a_double_quote_inside_feedback_still_gives_its_score(monkeypatch):
    broken = '{"score": 6, "feedback": "Say "fast" tests, not "sloppy"; add the late-fee point."}'
    monkeypatch.setattr(verify_node, "call_writer", lambda prompt, **kw: broken)

    result = verify_node.run_verify("transcript", "notes")

    assert result.score == 6
    assert "late-fee point" in result.feedback


def test_judge_reply_with_no_score_at_all_is_still_unparseable():
    assert verify_node._parse_verify_response("I think this section is fine overall.") is None


def test_a_caption_misspelling_of_a_name_still_counts_as_spoken():
    # Real 4-hour system-design book: captions said "kubernates" and "graphql",
    # and the notes' Kubernetes/Graph lines were deleted as "invented".
    transcript = "we deploy on kubernates and expose a graphql api"
    notes = "## Deploy\n- Run it on *Kubernetes* behind a *Graph* layer, not *Nomad*, *Mesos* or *Swarm*.\n"

    assert verify_node.find_unsupported_terms(notes, transcript) == ["nomad", "mesos", "swarm"]


_SPEECH = (
    "earlier in my life i used to do triathlons and i needed to get myself far enough ahead "
    "but now i can back off people loved it they told their friends they did not cancel "
    "three garlic nun three aloo roti one shahi panier for my friends"
)


def test_a_quote_box_the_speaker_never_said_is_removed_and_a_real_one_kept():
    notes = (
        "## Episode\n"
        '> Quote: "People loved it. They told their friends."\n'
        '> Quote: "Our churn dropped to zero overnight, which nobody expected."\n'
    )

    result = verify_node.drop_unspoken_quotes(notes, _SPEECH)

    assert "People loved it" in result
    assert "churn" not in result


def test_quotes_joined_with_an_ellipsis_are_checked_part_by_part():
    notes = '## T\n> Quote: "I needed to get myself far enough ahead … now I can back off"\n'

    assert verify_node.drop_unspoken_quotes(notes, _SPEECH) == notes.rstrip("\n")


def test_quoted_text_in_a_bullet_is_dropped_if_invented_and_unquoted_if_paraphrased():
    notes = (
        "## Bits\n"
        "- He orders “three garlic naan, three aloo roti, one shahi paneer” for everyone.\n"
        "- The model allowed free “store and ship back cycles with fixed fees”.\n"
        "- Plain bullet stays.\n"
    )

    result = verify_node.drop_unspoken_quotes(notes, _SPEECH)

    assert "- He orders three garlic naan, three aloo roti, one shahi paneer for everyone." in result
    assert "store and ship back" not in result
    assert "- Plain bullet stays." in result


def test_quote_check_is_skipped_for_a_non_english_transcript():
    notes = '## T\n> Quote: "A translated line from the Hindi talk."\n'

    assert verify_node.drop_unspoken_quotes(notes, _HINDI) == notes
