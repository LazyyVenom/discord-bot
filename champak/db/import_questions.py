"""Load the JSON question bank into the database.

Validation happens for a whole file before anything is written, so a single
malformed record aborts that file rather than half-loading it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from champak.db.models import Question

log = logging.getLogger(__name__)

DEFAULT_DIRECTORY = Path("data/questions")
LETTERS = ("A", "B", "C", "D")
_PART_SUFFIX = re.compile(r"_part\d+$")


class QuestionImportError(RuntimeError):
    """Raised when the source data cannot be trusted."""


@dataclass(frozen=True)
class ImportStats:
    files: int
    created: int
    updated: int


def category_for_filename(name: str) -> str:
    """`dsa_part1.json` -> `dsa`. Parts of a set share one category."""
    return _PART_SUFFIX.sub("", Path(name).stem)


def letter_for(answer_id: int) -> str:
    return LETTERS[answer_id - 1]


def import_key_for(question_text: str) -> str:
    """Stable identity for a question, so reruns update instead of duplicate."""
    normalised = " ".join(question_text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def shuffled_options(
    values: dict[int, str], answer_id: int, seed_key: str
) -> tuple[list[str], str]:
    """Reorder the four options deterministically.

    The source bank puts the correct answer at B in 84% of questions, so
    "always click B" scored 84% without reading anything. Seeding the shuffle
    with the question's import_key keeps it stable across reimports: the same
    question always lands on the same arrangement, so a user who retries after
    the cooldown sees what they saw before.

    Shuffles the option *ids* rather than the strings so duplicate option text
    cannot make us track the wrong one.
    """
    order = [1, 2, 3, 4]
    random.Random(seed_key).shuffle(order)
    return [values[i] for i in order], LETTERS[order.index(answer_id)]


def _validate(record: object, source: str, index: int) -> dict:
    where = f"{source} index {index}"

    if not isinstance(record, dict):
        raise QuestionImportError(f"{where}: expected an object, got {type(record).__name__}")

    text = str(record.get("question", "")).strip()
    if not text:
        raise QuestionImportError(f"{where}: missing question text")

    options = record.get("options")
    if not isinstance(options, list) or len(options) != 4:
        raise QuestionImportError(f"{where}: expected exactly 4 options")

    ids = sorted(o.get("option_id") for o in options)
    if ids != [1, 2, 3, 4]:
        raise QuestionImportError(f"{where}: option_ids must be 1-4, got {ids}")

    values = {o["option_id"]: str(o.get("option_value", "")).strip() for o in options}
    for oid, value in values.items():
        if not value:
            raise QuestionImportError(f"{where}: option {oid} is empty")

    answer_id = record.get("answer_id")
    if answer_id not in (1, 2, 3, 4):
        raise QuestionImportError(f"{where}: answer_id must be 1-4, got {answer_id!r}")

    explanation = str(record.get("answer_explanation", "")).strip()
    if not explanation:
        raise QuestionImportError(f"{where}: missing explanation")

    difficulty = record.get("difficulty_level")
    if not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
        raise QuestionImportError(f"{where}: difficulty must be 1-5, got {difficulty!r}")

    key = import_key_for(text)
    ordered, correct_letter = shuffled_options(values, answer_id, key)

    return {
        "title": text,
        "option_a": ordered[0],
        "option_b": ordered[1],
        "option_c": ordered[2],
        "option_d": ordered[3],
        "correct_option": correct_letter,
        "explanation": explanation,
        "difficulty": difficulty,
        "points": difficulty * 10,
        "category": category_for_filename(source),
        "import_key": key,
    }


def parse_file(path: Path) -> list[dict]:
    """Read and fully validate one file. Raises before returning anything."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QuestionImportError(f"{path.name}: invalid JSON - {exc}") from exc

    if not isinstance(raw, list):
        raise QuestionImportError(f"{path.name}: expected a top-level JSON array")

    return [_validate(record, path.name, i) for i, record in enumerate(raw)]


async def import_all(session, directory: Path = DEFAULT_DIRECTORY) -> ImportStats:
    """Validate every file, then upsert every question by import_key."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise QuestionImportError(f"{directory}: no JSON files found")

    # Validate everything up front so a bad file in the middle cannot leave a
    # partially-populated database behind.
    #
    # The bank genuinely repeats some questions across categories -- "What is
    # a REST API?" lives in both backend_concepts and system_design. Keying by
    # import_key collapses them so nobody is served the same question twice
    # under two ids. First file wins the category, which makes the result
    # depend on the sorted filename rather than on dict ordering.
    parsed: dict[str, dict] = {}
    for path in paths:
        for row in parse_file(path):
            parsed.setdefault(row["import_key"], row)

    existing = {
        q.import_key: q
        for q in (
            await session.execute(
                select(Question).where(Question.import_key.in_(parsed.keys()))
            )
        ).scalars()
    }

    created = updated = 0
    for key, row in parsed.items():
        question = existing.get(key)
        if question is None:
            session.add(Question(**row))
            created += 1
        else:
            for field, value in row.items():
                setattr(question, field, value)
            updated += 1

    await session.commit()
    log.info(
        "imported %d files: %d created, %d updated", len(paths), created, updated
    )
    return ImportStats(files=len(paths), created=created, updated=updated)


async def _main() -> None:
    import sys

    from champak.config import load_config
    from champak.db.session import create_engine_for, init_db, make_session_factory
    from champak.logging_setup import configure_logging

    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIRECTORY
    config = load_config()
    configure_logging(config.logging_level)

    engine = create_engine_for(config.db_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        stats = await import_all(session, directory)
    await engine.dispose()

    print(
        f"{stats.files} files -> {stats.created} created, {stats.updated} updated"
    )


if __name__ == "__main__":
    asyncio.run(_main())
