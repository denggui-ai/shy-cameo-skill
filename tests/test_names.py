from coshoot.names import NameEntry, classify, load_names, scan

ENTRIES = [
    NameEntry("六小龄童", ("章金莱",), {"character_id": "xiyou/wukong", "version_label": "版本标签A"}),
    NameEntry("周星驰", ("星爷", "Stephen Chow"), None),
]


def test_scan_chinese_substring_and_alias():
    assert [h.matched for h in scan("想和章金莱老师合影", ENTRIES)] == ["章金莱"]


def test_scan_ascii_is_case_insensitive_with_word_boundary():
    assert [h.matched for h in scan("a STEPHEN CHOW look", ENTRIES)] == ["Stephen Chow"]
    assert scan("stephen chowder", ENTRIES) == []


def test_classify_mappable_vs_blocked():
    result = classify("六小龄童版的悟空，再加上星爷", ENTRIES)
    assert result["mappable"] == [
        {"matched": "六小龄童", "character_id": "xiyou/wukong", "version_label": "版本标签A"}
    ]
    assert result["blocked"] == ["星爷"]


def test_shipped_list_loads_and_has_no_duplicate_terms():
    entries = load_names()
    terms = [t for e in entries for t in e.terms()]
    assert len(terms) == len(set(terms))
    assert any(e.name == "六小龄童" for e in entries)


def test_scan_normalises_whitespace_zero_width_and_fullwidth():
    assert [h.matched for h in scan("六 小龄童", ENTRIES)] == ["六小龄童"]
    assert [h.matched for h in scan("六​小龄童", ENTRIES)] == ["六小龄童"]
    assert [h.matched for h in scan("六﻿小⁠龄童", ENTRIES)] == ["六小龄童"]
    assert [h.matched for h in scan("ＳＴＥＰＨＥＮ ＣＨＯＷ", ENTRIES)] == ["Stephen Chow"]
    assert scan("stephen chowder", ENTRIES) == []


def test_scan_compact_ascii_and_format_controls():
    for text in ("StephenChow", "Stephen\u200bChow", "STEPHEN   CHOW", "Stephen\u200eChow"):
        assert [h.matched for h in scan(text, ENTRIES)] == ["Stephen Chow"], text
    assert scan("stephenchowder", ENTRIES) == []
    assert scan("stephen chowder", ENTRIES) == []
    assert [h.matched for h in scan("六小龄\u200e童", ENTRIES)] == ["六小龄童"]


def test_shipped_list_catches_traditional_and_compact_forms():
    entries = load_names()
    assert scan("周星馳", entries)
    assert scan("六小齡童", entries)
    assert scan("StephenChow", entries)
    assert scan("六小龄\u200e童", entries)
    assert scan("stephenchowder", entries) == []


def test_scan_folds_greek_and_cyrillic_lookalikes():
    for text in ("Stephen Chοw", "Stephen Сhow", "Ѕtephen Chow", "ЅTEPHEN СHOW"):
        assert [h.matched for h in scan(text, ENTRIES)] == ["Stephen Chow"], text


def test_confusable_folding_leaves_real_greek_alone():
    assert scan("λόγος και Ωμέγα", ENTRIES) == []


def test_real_actor_names_never_map_to_version_label():
    assert all(entry.maps_to is None for entry in load_names())
    result = classify("孙彦军演的刘备", load_names())
    assert result["blocked"]
    assert result["mappable"] == []


def test_scan_keeps_matches_when_lookalike_is_glued_to_the_name():
    for text in ("Stephen Chowа", "Stephen Chowом", "Ѕtephen Chowа", "Stephen Choԝ"):
        assert [h.matched for h in scan(text, ENTRIES)] == ["Stephen Chow"], text


def test_scan_compact_form_keeps_glued_lookalike_matches():
    for text in ("StephenСhowа", "Stephen  Сhowа", "Stephen​Сhowа", "Stephen Chowԁ"):
        assert [h.matched for h in scan(text, ENTRIES)] == ["Stephen Chow"], text
    assert scan("xStephenChow", ENTRIES) == []


def test_scan_collapses_whitespace_runs_after_ascii_word():
    for text in ("a Stephen  Chow", "costume by Stephen\tChow", "x Stephen\xa0\xa0Chow",
                 "a Stephen\u200b Chow", "Stephen \u200b\n Chow"):
        assert [h.matched for h in scan(text, ENTRIES)] == ["Stephen Chow"], text
    assert scan("xStephen Chow", ENTRIES) == []
    assert scan("Stephen Chowder", ENTRIES) == []
    assert scan("Stephen  Chowder", ENTRIES) == []


def test_cjk_name_glued_to_common_word_is_not_a_hit():
    entries = load_names()
    for text in ("托塔天王李靖飞身而来", "李靖飞行器", "孙彦军队的营帐", "汪粤语的台词", "李靖飛來"):
        assert scan(text, entries) == [], text


def test_cjk_name_still_caught_beside_ordinary_text():
    entries = load_names()
    for text in ("李靖飞版的造型", "要孙彦军演的那一版", "汪粤", "六 小 龄 童", "李靖飞行器和李靖飞版",
                 "李靖飞 行版", "孙彦军\n队", "李 靖 飞 行"):
        assert scan(text, entries), text
