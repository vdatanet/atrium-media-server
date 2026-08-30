# SPDX-License-Identifier: GPL-3.0-or-later
"""Every revision this build ships, applied and rolled back.

T4 tested revision `0001` by name. This walks **whatever the script directory holds**, so it keeps
working when 003 adds its own and nobody has to remember to extend it. That is the difference
between a test of a migration and a test of the migration history.

**Reversible means the schema comes back**, not that a `downgrade()` exists. A downgrade that runs
without error and leaves a table behind is worse than one that raises, because nothing says so. So
each revision is applied, rolled back, and the schema compared against what was there before it -
and a revision that does not restore has to **say so in its docstring and say why**, which is the
rule plan section 4 states and this is the thing that enforces it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import Script, ScriptDirectory
from sqlalchemy import Engine, inspect

from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine
from tests.conftest import data_dir

#: `0001_users_and_sessions`: zero-padded and ordered, so the directory reads in the order it
#: applies. plan section 4 names the first one in this form and every later one follows it.
REVISION_ID = re.compile(r"\A\d{4}\Z")

#: What a revision that cannot be rolled back has to contain. Spelled out rather than inferred,
#: because "the downgrade looked empty to me" is not a decision anybody made.
IRREVERSIBLE = "irreversible"

#: What a revision that rewrites **rows** rather than columns has to contain. `schema_of` reads the
#: schema, so a data migration is invisible to it and would otherwise be reported as a revision
#: that changed nothing - which is a real failure and the one this sweep exists to catch. The
#: allowance is the same shape as `IRREVERSIBLE` on purpose: the sweep cannot see the change, so
#: the revision declares it, and "changed nothing" stays a failure everywhere else. Added by 011
#: T2, whose `0007` is the first revision here that touches no schema.
DATA_ONLY = "data migration"


def revisions() -> list[Script]:
    """Every revision, oldest first."""
    config = schema.alembic_config(DataPaths(Path()))
    directory = ScriptDirectory.from_config(config)
    return list(reversed(list(directory.walk_revisions())))


def revision_ids() -> list[str]:
    return [one.revision for one in revisions()]


def schema_of(engine: Engine) -> dict[str, list[str]]:
    """Table to its columns and indexes, which is what "the schema came back" means here.

    **Nullability is part of a column's name here**, added by 004 T9. Revision 0004 changes one
    column from `NOT NULL` to nullable and nothing else, and this function could not see it: it
    recorded names, so "every revision changes the schema" reported that one as changing nothing.
    A sweep that cannot see a kind of change cannot prove that kind of change is reversible
    either, which is the more serious half.
    """
    with engine.connect() as connection:
        inspector = inspect(connection)
        found = {}
        for table in inspector.get_table_names():
            if table == schema.VERSION_TABLE:
                continue
            columns = sorted(
                f"{column['name']}{'' if column['nullable'] else ' NOT NULL'}"
                for column in inspector.get_columns(table)
            )
            indexes = sorted(index["name"] or "" for index in inspector.get_indexes(table))
            found[table] = columns + [f"index:{name}" for name in indexes]
    return found


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(paths: DataPaths) -> Iterator[Engine]:
    built = create_database_engine(paths)
    yield built
    built.dispose()


def move(engine: Engine, paths: DataPaths, target: str) -> None:
    """Upgrade or downgrade to `target`, over the engine that has the pragmas attached."""
    config = schema.alembic_config(paths)
    directory = ScriptDirectory.from_config(config)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        current = schema.current_revision(engine)
        if target == "base":
            command.downgrade(config, "base")
            return
        known = [one.revision for one in reversed(list(directory.walk_revisions()))]
        if current is not None and known.index(target) < known.index(current):
            command.downgrade(config, target)
        else:
            command.upgrade(config, target)


# --------------------------------------------------------------------------------------------
# The sweep is a sweep
# --------------------------------------------------------------------------------------------


def test_the_history_has_revisions_and_exactly_one_head() -> None:
    """A sweep over nothing passes, and two heads mean a merge nobody made."""
    found = revisions()
    assert found, "no revisions found; the script directory or its configuration changed shape"
    config = schema.alembic_config(DataPaths(Path()))
    assert ScriptDirectory.from_config(config).get_current_head() == found[-1].revision


@pytest.mark.parametrize("revision", revision_ids())
def test_every_revision_is_numbered_in_order(revision: str) -> None:
    """`0001`, `0002`, and so on: zero-padded, so the directory reads in the order it applies."""
    assert REVISION_ID.match(revision), f"{revision} is not a zero-padded number"


def test_the_numbers_run_without_a_gap() -> None:
    numbers = [int(one) for one in revision_ids()]
    assert numbers == list(range(1, len(numbers) + 1)), f"the history numbers {numbers}"


# --------------------------------------------------------------------------------------------
# Up, and back down, one revision at a time
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("revision", revision_ids())
def test_every_revision_applies_and_rolls_back(
    engine: Engine, paths: DataPaths, revision: str
) -> None:
    """Applied, rolled back, and the schema compared against what was there before it.

    A `downgrade()` that runs without error and leaves a table behind passes any test that only
    checks it did not raise. This one notices.
    """
    script = next(one for one in revisions() if one.revision == revision)
    previous = script.down_revision or "base"
    docstring = ((script.doc or "") + (script.longdoc or "")).lower()

    if previous != "base":
        move(engine, paths, str(previous))
    before = schema_of(engine)

    move(engine, paths, revision)
    after = schema_of(engine)
    assert after != before or not after or DATA_ONLY in docstring, (
        f"{revision} changed nothing. A revision that rewrites rows rather than columns is "
        f"allowed - it has to declare itself a {DATA_ONLY!r} in its docstring, because this "
        f"sweep reads the schema and cannot see what it did"
    )

    move(engine, paths, str(previous))
    back = schema_of(engine)

    if back != before:
        assert IRREVERSIBLE in docstring, (
            f"{revision} does not restore the schema and does not say so. A migration that cannot "
            f"be reversed is allowed - it has to declare it in its docstring and say why, so that "
            f"irreversibility is a decision rather than an oversight (plan section 4). "
            f"Left behind: {sorted(set(back) - set(before))}"
        )


# --------------------------------------------------------------------------------------------
# The whole history, in both directions
# --------------------------------------------------------------------------------------------


def test_the_whole_history_walks_up_and_all_the_way_back_down(
    engine: Engine, paths: DataPaths
) -> None:
    move(engine, paths, "head")
    assert schema_of(engine), "upgrading to head created nothing"

    move(engine, paths, "base")
    remaining = schema_of(engine)
    assert remaining == {}, f"walking back to base left {sorted(remaining)} behind"


def test_the_history_replays_to_the_same_schema(engine: Engine, paths: DataPaths) -> None:
    """Up, down, up again. A migration that is not idempotent in this sense makes a restored
    backup and a fresh install two different databases."""
    move(engine, paths, "head")
    first = schema_of(engine)
    move(engine, paths, "base")
    move(engine, paths, "head")
    assert schema_of(engine) == first


# --------------------------------------------------------------------------------------------
# 0007, which is the only revision here that moves rows instead of columns
# --------------------------------------------------------------------------------------------


#: What 008 stored, and what 011 T2 renames it to. Asserted here on the **value**, because two of
#: the four answer the text/image split identically before and after the rename - so a test that
#: checked the split would pass with half the rewrite deleted. The disagreement itself is
#: `tests/unit/test_media_info.py`'s table.
CODEC_RENAMES = (
    ("dvb_subtitle", "DVBSUB"),
    ("dvb_teletext", "DVBTXT"),
    ("dvd_subtitle", "DVDSUB"),
    ("hdmv_pgs_subtitle", "PGSSUB"),
)


def seed_streams(engine: Engine) -> None:
    """One probed file, with one subtitle row per rename plus two rows the rewrite must not
    touch: a `subrip` subtitle, and a **video** stream whose codec is spelled like one of the
    four - which is the row that fails if the `type` clause is dropped."""
    named = [raw for raw, _ in CODEC_RENAMES]
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO libraries (id, name, collection_type) VALUES (:i, :n, 'movies')"),
            {"i": "1" * 32, "n": "Films"},
        )
        connection.execute(
            sa.text(
                "INSERT INTO media_probes (library_id, relative_path, size, mtime_ns, container,"
                " format_names, probed_at) VALUES (:l, 'A Film.mkv', 1, 1, 'mkv', 'matroska,webm',"
                " '2026-08-30 00:00:00.000000+00:00')"
            ),
            {"l": "1" * 32},
        )
        rows = [{"i": index, "t": "subtitle", "c": codec} for index, codec in enumerate(named)] + [
            {"i": len(named), "t": "subtitle", "c": "subrip"},
            {"i": len(named) + 1, "t": "video", "c": "dvd_subtitle"},
        ]
        for row in rows:
            connection.execute(
                sa.text(
                    "INSERT INTO media_streams (library_id, relative_path, stream_index, type,"
                    " codec) VALUES (:l, 'A Film.mkv', :i, :t, :c)"
                ),
                {"l": "1" * 32, **row},
            )


def codecs(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as connection:
        return [
            (str(one), str(two))
            for one, two in connection.execute(
                sa.text("SELECT type, codec FROM media_streams ORDER BY stream_index")
            ).all()
        ]


def test_0007_rewrites_the_four_subtitle_spellings_and_puts_them_back(
    engine: Engine, paths: DataPaths
) -> None:
    """The rewrite, up and down, against rows written the way a 008 scan wrote them.

    Asserted on the stored **value**, not on anything derived from it: `hdmv_pgs_subtitle` already
    contains `pgs` and `dvb_teletext` is text either way, so a test that only checked the
    text/image split would pass with the whole migration deleted.
    """
    move(engine, paths, "0006")
    seed_streams(engine)
    before = codecs(engine)
    assert before == [
        *(("subtitle", raw) for raw, _ in CODEC_RENAMES),
        ("subtitle", "subrip"),
        ("video", "dvd_subtitle"),
    ]

    move(engine, paths, "0007")
    assert codecs(engine) == [
        *(("subtitle", renamed) for _, renamed in CODEC_RENAMES),
        ("subtitle", "subrip"),
        ("video", "dvd_subtitle"),
    ], "a subtitle spelling was missed, or a stream that is not a subtitle was renamed"

    move(engine, paths, "0006")
    assert codecs(engine) == before, "the downgrade did not put the spellings back"


def test_0007_replayed_over_the_same_rows_lands_on_the_same_values(
    engine: Engine, paths: DataPaths
) -> None:
    """Up, down, up, over rows rather than over columns.

    The schema half of this is `test_the_history_replays_to_the_same_schema`; a data migration
    needs the same claim made about what it wrote, because a restored backup and a fresh install
    otherwise differ in the rows.
    """
    move(engine, paths, "0006")
    seed_streams(engine)

    move(engine, paths, "0007")
    once = codecs(engine)
    move(engine, paths, "0006")
    move(engine, paths, "0007")

    assert codecs(engine) == once


def test_0007_writes_names_it_does_not_read_which_is_why_running_it_twice_is_safe() -> None:
    """What the test above cannot reach, stated as the property it rests on.

    Alembic stamps a revision, so nothing here can apply `0007` twice in a row - and "a database
    migrated twice is a database migrated once" is not a claim about Alembic. It is a claim about
    the table: the names the rewrite looks for and the names it writes are **disjoint**, in both
    directions, so a second pass over the same rows would match nothing.
    """
    renamed = next(one for one in revisions() if one.revision == "0007").module.RENAMED

    reads = {one.lower() for one in renamed}
    writes = {one.lower() for one in renamed.values()}
    assert not reads & writes
    assert dict(CODEC_RENAMES) == renamed, (
        "this file's table and the migration's have drifted apart"
    )


#: A second revision that does nothing at all and declares nothing - the failure the `DATA_ONLY`
#: allowance must not have turned off. `0001` is here only so that the schema is non-empty by the
#: time `0002` is asked to change it.
IDLE = '''"""adds nothing and says nothing about it

Revision ID: {revision}
Revises: {down}
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "{revision}"
down_revision = {down!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    {up}


def downgrade() -> None:
    {down_body}
'''


def test_the_sweep_still_fails_a_revision_that_changes_nothing_and_says_nothing(
    engine: Engine, paths: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the `DATA_ONLY` allowance: it is a declaration, not an escape.

    A revision whose `upgrade()` does nothing and whose docstring says nothing still has to fail,
    or one line added for `0007` would have switched the sweep's sharpest assertion off for every
    revision at once. The condition is evaluated here rather than restated, so it cannot drift
    from the one the sweep uses.
    """
    import shutil

    location = tmp_path / "idle"
    (location / "versions").mkdir(parents=True)
    shutil.copy(schema.SCRIPT_LOCATION / "env.py", location / "env.py")
    shutil.copy(schema.SCRIPT_LOCATION / "script.py.mako", location / "script.py.mako")
    (location / "versions" / "0001_kept.py").write_text(
        IDLE.format(
            revision="0001",
            down=None,
            up='op.create_table("kept", sa.Column("id", sa.Integer(), primary_key=True))',
            down_body='op.drop_table("kept")',
        ),
        encoding="utf-8",
    )
    (location / "versions" / "0002_idle.py").write_text(
        IDLE.format(revision="0002", down="0001", up="pass", down_body="pass"),
        encoding="utf-8",
    )
    monkeypatch.setattr(schema, "SCRIPT_LOCATION", location)

    move(engine, paths, "0001")
    before = schema_of(engine)
    move(engine, paths, "0002")
    after = schema_of(engine)

    script = next(one for one in revisions() if one.revision == "0002")
    docstring = ((script.doc or "") + (script.longdoc or "")).lower()
    assert not (after != before or not after or DATA_ONLY in docstring), (
        "the sweep would have let a revision that does nothing through"
    )


def test_upgrading_from_an_empty_file_reaches_head(paths: DataPaths) -> None:
    """The path an operator actually takes: a restore that copied a zero-byte database, or a
    volume mount that created the path."""
    paths.database.write_bytes(b"")
    engine = create_database_engine(paths)
    try:
        schema.ensure_current(engine, paths)
        assert schema.current_revision(engine) == revision_ids()[-1]
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------------
# The rule itself
# --------------------------------------------------------------------------------------------


#: A revision whose `downgrade()` runs cleanly and leaves a table behind - the failure that passes
#: any test which only checks that rolling back did not raise.
LEAKY = '''"""adds two tables and forgets one on the way down

Revision ID: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("kept", sa.Column("id", sa.Integer(), primary_key=True))
    op.create_table("leftover", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    op.drop_table("kept")
'''


def test_the_sweep_catches_a_downgrade_that_leaves_a_table_behind(
    engine: Engine, paths: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard that cannot fail is decoration, and this is the failure it exists for.

    The revision below rolls back without raising and leaves `leftover` in the database. Every
    test that checks only "the downgrade did not error" passes against it.
    """
    import shutil

    location = tmp_path / "leaky"
    (location / "versions").mkdir(parents=True)
    shutil.copy(schema.SCRIPT_LOCATION / "env.py", location / "env.py")
    shutil.copy(schema.SCRIPT_LOCATION / "script.py.mako", location / "script.py.mako")
    (location / "versions" / "0001_leaky.py").write_text(LEAKY, encoding="utf-8")
    monkeypatch.setattr(schema, "SCRIPT_LOCATION", location)

    before = schema_of(engine)
    move(engine, paths, "0001")
    assert set(schema_of(engine)) == {"kept", "leftover"}

    move(engine, paths, "base")
    back = schema_of(engine)

    assert back != before, "the sweep would not have noticed the leftover table"
    assert set(back) == {"leftover"}

    script = next(one for one in revisions() if one.revision == "0001")
    docstring = (script.doc or "") + (script.longdoc or "")
    assert IRREVERSIBLE not in docstring.lower(), (
        "this fixture is meant to be the *silent* case; a revision that declares itself "
        "irreversible is allowed to leave things behind"
    )


def test_a_revision_that_declares_itself_is_allowed_to_leave_things_behind() -> None:
    """The other half of the rule: irreversibility is permitted, and it has to be a decision."""
    declared = "drops a column. Irreversible: SQLite cannot restore the data that was in it."
    assert IRREVERSIBLE in declared.lower()
    assert IRREVERSIBLE not in "adds a table".lower()
