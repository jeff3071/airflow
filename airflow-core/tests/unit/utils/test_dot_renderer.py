#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

from unittest import mock

import pytest

from airflow.models.dag import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.serialization.dag_dependency import DagDependency
from airflow.utils import dot_renderer, timezone
from airflow.utils.state import State
from airflow.utils.task_group import TaskGroup

from tests_common.test_utils.compat import BashOperator
from tests_common.test_utils.db import clear_db_dags

try:
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:
    from airflow.operators.python import PythonOperator  # type: ignore[no-redef]

START_DATE = timezone.utcnow()

pytestmark = pytest.mark.db_test


class TestDotRenderer:
    def setup_class(self):
        clear_db_dags()

    def teardown_method(self):
        clear_db_dags()

    def test_should_render_dag_dependencies(self):
        dag_dep_1 = DagDependency(
            source="dag_one",
            target="dag_two",
            label="task_1",
            dependency_type="sensor",
            dependency_id="task_1",
        )
        dag_dep_2 = DagDependency(
            source="dag_two",
            target="dag_three",
            label="task_2",
            dependency_type="sensor",
            dependency_id="task_2",
        )

        dag_dependency_list = [dag_dep_1, dag_dep_2]

        dag_dependency_dict = {}
        dag_dependency_dict["dag_one"] = dag_dependency_list
        dot = dot_renderer.render_dag_dependencies(dag_dependency_dict)

        assert "dag_one -> task_1" in dot.source
        assert "task_1 -> dag_two" in dot.source
        assert "dag_two -> task_2" in dot.source
        assert "task_2 -> dag_three" in dot.source

    def test_should_render_dag(self):
        with DAG(dag_id="DAG_ID", schedule=None) as dag:
            task_1 = BashOperator(start_date=START_DATE, task_id="first", bash_command="echo 1")
            task_2 = BashOperator(start_date=START_DATE, task_id="second", bash_command="echo 1")
            task_3 = PythonOperator(start_date=START_DATE, task_id="third", python_callable=mock.MagicMock())
            task_1 >> task_2
            task_1 >> task_3

        dot = dot_renderer.render_dag(dag)
        source = dot.source
        # Should render DAG title
        assert "label=DAG_ID" in source
        assert "first" in source
        assert "second" in source
        assert "third" in source
        assert "first -> second" in source
        assert "first -> third" in source
        assert 'fillcolor="#f0ede4"' in source
        assert 'fillcolor="#f0ede4"' in source

    def test_should_render_dag_with_task_instances(self, session, dag_maker):
        with dag_maker(dag_id="DAG_ID", session=session) as dag:
            task_1 = BashOperator(start_date=START_DATE, task_id="first", bash_command="echo 1")
            task_2 = BashOperator(start_date=START_DATE, task_id="second", bash_command="echo 1")
            task_3 = PythonOperator(start_date=START_DATE, task_id="third", python_callable=mock.MagicMock())
            task_1 >> task_2
            task_1 >> task_3

        tis = {ti.task_id: ti for ti in dag_maker.create_dagrun(logical_date=START_DATE).task_instances}
        tis["first"].state = State.SCHEDULED
        tis["second"].state = State.SUCCESS
        tis["third"].state = State.RUNNING

        dot = dot_renderer.render_dag(dag, tis=tis.values())
        source = dot.source
        # Should render DAG title
        assert "label=DAG_ID" in source
        assert (
            'first [color=black fillcolor=tan label=first shape=rectangle style="filled,rounded"]' in source
        )
        assert (
            'second [color=white fillcolor=green label=second shape=rectangle style="filled,rounded"]'
            in source
        )
        assert (
            'third [color=black fillcolor=lime label=third shape=rectangle style="filled,rounded"]' in source
        )

    def test_should_render_dag_with_mapped_operator(self, session, dag_maker):
        with dag_maker(dag_id="DAG_ID", session=session) as dag:
            BashOperator.partial(task_id="first", task_display_name="First Task").expand(
                bash_command=["echo hello", "echo world"]
            )

        dot = dot_renderer.render_dag(dag)
        source = dot.source
        # Should render DAG title
        assert "label=DAG_ID" in source
        assert (
            'first [color="#000000" fillcolor="#f0ede4" label="First Task" shape=rectangle style="filled,rounded"]'
            in source
        )

    def test_render_task_group(self):
        with DAG(dag_id="example_task_group", schedule=None, start_date=START_DATE) as dag:
            start = EmptyOperator(task_id="start")

            with TaskGroup("section_1", tooltip="Tasks for section_1") as section_1:
                task_1 = EmptyOperator(task_id="task_1")
                task_2 = BashOperator(task_id="task_2", bash_command="echo 1")
                task_3 = EmptyOperator(task_id="task_3")

                task_1 >> [task_2, task_3]

            with TaskGroup("section_2", tooltip="Tasks for section_2") as section_2:
                task_1 = EmptyOperator(task_id="task_1")

                with TaskGroup("inner_section_2", tooltip="Tasks for inner_section2"):
                    task_2 = BashOperator(task_id="task_2", bash_command="echo 1")
                    task_3 = EmptyOperator(task_id="task_3")
                    task_4 = EmptyOperator(task_id="task_4")

                    [task_2, task_3] >> task_4

            end = EmptyOperator(task_id="end")

            start >> section_1 >> section_2 >> end

        dot = dot_renderer.render_dag(dag)

        assert dot.source.strip() == "\n".join(
            [
                "digraph example_task_group {",
                "\tgraph [label=example_task_group labelloc=t rankdir=LR]",
                '\tend [color="#000000" fillcolor="#e8f7e4" label=end shape=rectangle '
                'style="filled,rounded"]',
                "\tsubgraph cluster_section_1 {",
                '\t\tcolor="#000000" fillcolor="#6495ed7f" label=section_1 shape=rectangle style=filled',
                '\t\t"section_1.upstream_join_id" [color="#000000" fillcolor=CornflowerBlue height=0.2 '
                'label="" shape=circle style="filled,rounded" width=0.2]',
                '\t\t"section_1.downstream_join_id" [color="#000000" fillcolor=CornflowerBlue height=0.2 '
                'label="" shape=circle style="filled,rounded" width=0.2]',
                '\t\t"section_1.task_1" [color="#000000" fillcolor="#e8f7e4" label=task_1 shape=rectangle '
                'style="filled,rounded"]',
                '\t\t"section_1.task_2" [color="#000000" fillcolor="#f0ede4" label=task_2 shape=rectangle '
                'style="filled,rounded"]',
                '\t\t"section_1.task_3" [color="#000000" fillcolor="#e8f7e4" label=task_3 shape=rectangle '
                'style="filled,rounded"]',
                "\t}",
                "\tsubgraph cluster_section_2 {",
                '\t\tcolor="#000000" fillcolor="#6495ed7f" label=section_2 shape=rectangle style=filled',
                '\t\t"section_2.upstream_join_id" [color="#000000" fillcolor=CornflowerBlue height=0.2 '
                'label="" shape=circle style="filled,rounded" width=0.2]',
                '\t\t"section_2.downstream_join_id" [color="#000000" fillcolor=CornflowerBlue height=0.2 '
                'label="" shape=circle style="filled,rounded" width=0.2]',
                '\t\tsubgraph "cluster_section_2.inner_section_2" {',
                '\t\t\tcolor="#000000" fillcolor="#6495ed7f" label=inner_section_2 shape=rectangle '
                "style=filled",
                '\t\t\t"section_2.inner_section_2.task_2" [color="#000000" fillcolor="#f0ede4" label=task_2 '
                'shape=rectangle style="filled,rounded"]',
                '\t\t\t"section_2.inner_section_2.task_3" [color="#000000" fillcolor="#e8f7e4" label=task_3 '
                'shape=rectangle style="filled,rounded"]',
                '\t\t\t"section_2.inner_section_2.task_4" [color="#000000" fillcolor="#e8f7e4" label=task_4 '
                'shape=rectangle style="filled,rounded"]',
                "\t\t}",
                '\t\t"section_2.task_1" [color="#000000" fillcolor="#e8f7e4" label=task_1 shape=rectangle '
                'style="filled,rounded"]',
                "\t}",
                '\tstart [color="#000000" fillcolor="#e8f7e4" label=start shape=rectangle '
                'style="filled,rounded"]',
                '\t"section_1.downstream_join_id" -> "section_2.upstream_join_id"',
                '\t"section_1.task_1" -> "section_1.task_2"',
                '\t"section_1.task_1" -> "section_1.task_3"',
                '\t"section_1.task_2" -> "section_1.downstream_join_id"',
                '\t"section_1.task_3" -> "section_1.downstream_join_id"',
                '\t"section_1.upstream_join_id" -> "section_1.task_1"',
                '\t"section_2.downstream_join_id" -> end',
                '\t"section_2.inner_section_2.task_2" -> "section_2.inner_section_2.task_4"',
                '\t"section_2.inner_section_2.task_3" -> "section_2.inner_section_2.task_4"',
                '\t"section_2.inner_section_2.task_4" -> "section_2.downstream_join_id"',
                '\t"section_2.task_1" -> "section_2.downstream_join_id"',
                '\t"section_2.upstream_join_id" -> "section_2.inner_section_2.task_2"',
                '\t"section_2.upstream_join_id" -> "section_2.inner_section_2.task_3"',
                '\t"section_2.upstream_join_id" -> "section_2.task_1"',
                '\tstart -> "section_1.upstream_join_id"',
                "}",
            ]
        )
