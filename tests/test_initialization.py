import importlib.util
import subprocess
from dataclasses import replace
from unittest.mock import patch

import pytest

from pg_workload.assets import bundled_profiles_root
from pg_workload.common import load_yaml
from pg_workload.initialization import LoadPlan, LoadTask, batches, ordered_tasks, run_plan
from pg_workload.profiles import Profile


def profile_plan(name, scale):
    path = bundled_profiles_root() / name / "generator.py"
    spec = importlib.util.spec_from_file_location(f"generator_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_load_plan(scale)


@pytest.mark.parametrize("profile", ["pagila", "imdb"])
def test_bundled_plans_validate_at_small_and_large_scales(profile):
    for scale in (0.001, 1, 10_000):
        plan = profile_plan(profile, scale)
        for tasks in (plan.data, plan.indexes, plan.constraints):
            assert len(ordered_tasks(tasks)) == len(tasks)
        for task in plan.data:
            first = next(batches(task, 137), None)
            assert first is not None
            if task.count is not None:
                assert "$1" not in first[1] and "$2" not in first[1]


def test_batches_cover_keys_once_and_bound_fanout():
    task = LoadTask("actors", "SELECT $1::bigint, $2::bigint", count=11, max_rows_per_key=3)
    assert list(batches(task, 12)) == [
        ("actors [1..4]", "SELECT 1::bigint, 4::bigint"),
        ("actors [5..8]", "SELECT 5::bigint, 8::bigint"),
        ("actors [9..11]", "SELECT 9::bigint, 11::bigint"),
    ]
    assert list(batches(replace(task, count=0), 12)) == []


def test_loader_commits_batches_before_indexes_and_finalization():
    plan = LoadPlan(
        schemas=("example",),
        schema_sql="CREATE SCHEMA example; CREATE TABLE example.items(id bigint);",
        prepare_sql="SELECT 'prepare';",
        # Input order is deliberately reversed: dependency ordering must precede batching.
        data=(
            LoadTask("dependent", "SELECT 'dependent';", depends_on=("items",)),
            LoadTask("items", "INSERT INTO items SELECT generate_series($1::bigint, $2::bigint);", count=5),
        ),
        after_data_sql="SELECT 'after data';",
        indexes=(LoadTask("items_pk", "CREATE UNIQUE INDEX items_pk ON items(id) -- no terminator"),),
        constraints=(LoadTask("items_pk", "ALTER TABLE items ADD PRIMARY KEY USING INDEX items_pk;"),),
        finalize_sql="SELECT 'finalize';",
    )
    with patch("pg_workload.initialization.subprocess.run") as run:
        run_plan(plan, batch_rows=2)
    sql = [call.kwargs["input"] for call in run.call_args_list]
    assert all(statement.startswith('SET search_path TO "example", public;\nBEGIN;\n') for statement in sql)
    assert all(statement.endswith("\nCOMMIT;\n") for statement in sql)
    assert "generate_series(1::bigint, 2::bigint)" in sql[2]
    assert "generate_series(3::bigint, 4::bigint)" in sql[3]
    assert "generate_series(5::bigint, 5::bigint)" in sql[4]
    assert "dependent" in sql[5]
    assert "after data" in sql[6]
    assert "CREATE UNIQUE INDEX" in sql[7]
    assert "-- no terminator\n;\nCOMMIT;" in sql[7]
    assert "ADD PRIMARY KEY" in sql[8]
    assert "finalize" in sql[9]
    assert "ANALYZE %I.%I" in sql[10]


def test_loader_aborts_after_failed_batch():
    plan = LoadPlan(
        schemas=("example",),
        schema_sql="CREATE SCHEMA example;",
        data=(LoadTask("broken", "SELECT $1, $2;", count=10),),
        indexes=(LoadTask("must_not_run", "SELECT 42;"),),
    )
    with patch("pg_workload.initialization.subprocess.run") as run:
        run.side_effect = [None, subprocess.CalledProcessError(3, "psql")]
        with pytest.raises(RuntimeError, match=r"data: broken \[1..2\]"):
            run_plan(plan, batch_rows=2)
    assert run.call_count == 2


@pytest.mark.parametrize(
    "tasks",
    [
        (LoadTask("a", "SELECT 1;", depends_on=("b",)),),
        (LoadTask("a", "SELECT 1;", depends_on=("a",)),),
        (LoadTask("a", "SELECT 1;"), LoadTask("a", "SELECT 2;")),
    ],
)
def test_invalid_plan_is_rejected_before_schema_reset(tasks):
    plan = LoadPlan(schemas=("example",), schema_sql="CREATE SCHEMA example;", data=tasks, indexes=())
    with patch("pg_workload.initialization.subprocess.run") as run, pytest.raises(ValueError):
        run_plan(plan)
    run.assert_not_called()


def test_pagila_declares_weighted_scripts_without_repeated_seed():
    root = bundled_profiles_root() / "pagila"
    profile = Profile(root, load_yaml(root / "profile.yml"))
    job = profile.job_by_name("main")
    assert [script["weight"] for script in profile.expand_scripts(job)] == [50, 25, 20, 5]
    assert not any("random-seed" in arg for arg in job.get("extra_args", []))
    assert not (root.parent / "pagila-htap").exists()
