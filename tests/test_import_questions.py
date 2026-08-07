import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from champak.db.import_questions import (
    QuestionImportError,
    category_for_filename,
    import_all,
    import_key_for,
    letter_for,
    parse_file,
)
from champak.db.models import Question

REAL_DATA = Path("data/questions")


def record(**kw):
    base = {
        "question": "What is 2+2?",
        "options": [
            {"option_id": 1, "option_value": "3"},
            {"option_id": 2, "option_value": "4"},
            {"option_id": 3, "option_value": "5"},
            {"option_id": 4, "option_value": "6"},
        ],
        "answer_id": 2,
        "answer_explanation": "Two plus two is four.",
        "difficulty_level": 1,
    }
    return {**base, **kw}


def write(tmp_path, name, records):
    p = tmp_path / name
    p.write_text(json.dumps(records))
    return p


# ---- pure helpers ----

@pytest.mark.parametrize("name,expected", [
    ("dsa_part1.json", "dsa"),
    ("dsa_part2.json", "dsa"),
    ("python.json", "python"),
    ("backend_concepts_part1.json", "backend_concepts"),
    ("javascript_typescript.json", "javascript_typescript"),
    ("system_design_part2.json", "system_design"),
])
def test_category_for_filename(name, expected):
    assert category_for_filename(name) == expected


@pytest.mark.parametrize("aid,letter", [(1, "A"), (2, "B"), (3, "C"), (4, "D")])
def test_letter_for(aid, letter):
    assert letter_for(aid) == letter


def test_import_key_is_stable_and_whitespace_insensitive():
    assert import_key_for("What is 2+2?") == import_key_for("  What is 2+2?  ")


def test_import_key_differs_by_text():
    assert import_key_for("a") != import_key_for("b")


# ---- parse_file validation ----

def test_parse_file_accepts_valid(tmp_path):
    assert len(parse_file(write(tmp_path, "dsa_part1.json", [record()]))) == 1


def test_parse_file_rejects_missing_explanation(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(answer_explanation="")])
    with pytest.raises(QuestionImportError, match="explanation"):
        parse_file(p)


def test_parse_file_rejects_wrong_option_count(tmp_path):
    p = write(tmp_path, "dsa_part1.json",
              [record(options=[{"option_id": 1, "option_value": "x"}])])
    with pytest.raises(QuestionImportError, match="4 options"):
        parse_file(p)


def test_parse_file_rejects_answer_id_out_of_range(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(answer_id=9)])
    with pytest.raises(QuestionImportError, match="answer_id"):
        parse_file(p)


def test_parse_file_rejects_bad_difficulty(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(difficulty_level=0)])
    with pytest.raises(QuestionImportError, match="difficulty"):
        parse_file(p)


def test_parse_file_rejects_blank_question(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(question="  ")])
    with pytest.raises(QuestionImportError, match="question text"):
        parse_file(p)


def test_error_names_the_file_and_index(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(), record(answer_id=9)])
    with pytest.raises(QuestionImportError, match=r"dsa_part1\.json.*index 1"):
        parse_file(p)


# ---- import_all ----

async def test_import_maps_all_fields(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record()])
    await import_all(session, tmp_path)

    q = (await session.execute(select(Question))).scalar_one()
    assert q.title == "What is 2+2?"
    assert (q.option_a, q.option_b, q.option_c, q.option_d) == ("3", "4", "5", "6")
    assert q.correct_option == "B"
    assert q.explanation == "Two plus two is four."
    assert q.category == "dsa"
    assert q.difficulty == 1
    assert q.points == 10
    assert q.description is None
    assert q.import_key == import_key_for("What is 2+2?")


async def test_points_derived_from_difficulty(session, tmp_path):
    write(tmp_path, "dsa_part1.json",
          [record(question=f"Q{d}", difficulty_level=d) for d in (1, 3, 5)])
    await import_all(session, tmp_path)

    rows = (await session.execute(select(Question).order_by(Question.difficulty))).scalars().all()
    assert [(r.difficulty, r.points) for r in rows] == [(1, 10), (3, 30), (5, 50)]


async def test_parts_merge_into_one_category(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record(question="Q1")])
    write(tmp_path, "dsa_part2.json", [record(question="Q2")])
    await import_all(session, tmp_path)

    cats = (await session.execute(select(Question.category).distinct())).scalars().all()
    assert cats == ["dsa"]


async def test_rerun_is_idempotent(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record()])
    first = await import_all(session, tmp_path)
    second = await import_all(session, tmp_path)

    assert (first.created, first.updated) == (1, 0)
    assert (second.created, second.updated) == (0, 1)
    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 1


async def test_rerun_updates_changed_explanation(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record()])
    await import_all(session, tmp_path)
    write(tmp_path, "dsa_part1.json", [record(answer_explanation="Revised.")])
    await import_all(session, tmp_path)

    q = (await session.execute(select(Question))).scalar_one()
    assert q.explanation == "Revised."


async def test_invalid_file_inserts_nothing(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record(), record(question="Q2", answer_id=9)])
    with pytest.raises(QuestionImportError):
        await import_all(session, tmp_path)

    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 0


async def test_duplicate_text_within_run_is_collapsed(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record(), record()])
    await import_all(session, tmp_path)
    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 1


async def test_duplicate_across_files_keeps_first_category(session, tmp_path):
    # The real bank repeats questions across categories; the first file in
    # sorted order must win so the result is deterministic.
    write(tmp_path, "aaa_first.json", [record()])
    write(tmp_path, "zzz_second.json", [record()])
    await import_all(session, tmp_path)

    q = (await session.execute(select(Question))).scalar_one()
    assert q.category == "aaa_first"


async def test_missing_directory_raises(session, tmp_path):
    with pytest.raises(QuestionImportError, match="no JSON files"):
        await import_all(session, tmp_path / "nope")


# ---- the real bank ----

@pytest.mark.skipif(not REAL_DATA.exists(), reason="question bank not present")
async def test_real_bank_imports_cleanly(session):
    # 1500 records in the files, but 52 question texts appear twice (54 extra
    # copies) -- mostly security and API questions duplicated between
    # backend_concepts and system_design. Dedup by import_key collapses those.
    stats = await import_all(session, REAL_DATA)
    assert stats.files == 10
    assert stats.created == 1446

    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 1446

    cats = sorted((await session.execute(select(Question.category).distinct())).scalars().all())
    assert cats == [
        "backend_concepts", "dsa", "javascript_typescript",
        "oops_lld", "python", "system_design",
    ]

    bad = (await session.execute(
        select(func.count()).select_from(Question).where(
            Question.explanation.is_(None) | (Question.explanation == "")
        )
    )).scalar_one()
    assert bad == 0
