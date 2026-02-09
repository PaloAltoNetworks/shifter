"""Tests for SQS event handler dispatch."""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from cms.experiments.handlers import _parse_message, process_event
from cms.experiments.models import Experiment, ExperimentRun
from cms.experiments.schemas import ExperimentStatus, RunStatus

# Test password constant for all test users
TEST_PASSWORD = "test"  # nosec B105


class ParseMessageTest(TestCase):
    def test_direct_dict(self):
        result = _parse_message({"event_type": "test"})
        assert result["event_type"] == "test"

    def test_json_string(self):
        result = _parse_message('{"event_type": "test"}')
        assert result["event_type"] == "test"

    def test_sns_envelope(self):
        envelope = {"Message": json.dumps({"event_type": "test"})}
        result = _parse_message(envelope)
        assert result["event_type"] == "test"


class ProcessEventTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="handler_user", password=TEST_PASSWORD, is_staff=True)

    def test_ignores_unknown_event(self):
        # Should not raise
        process_event({"event_type": "unknown.event", "event_id": "123"})

    def test_experiment_start_schedules_runs(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Start Handler",
            scenario_id="basic",
            total_runs=2,
            max_parallel_runs=2,
        )
        exp.transition_to(ExperimentStatus.QUEUED)
        for i in range(1, 3):
            ExperimentRun.objects.create(experiment=exp, run_number=i)

        process_event(
            {
                "event_type": "experiment.start",
                "experiment_id": exp.pk,
            }
        )

        exp.refresh_from_db()
        assert exp.status == ExperimentStatus.RUNNING.value

    def test_run_failed_event(self):
        exp = Experiment.objects.create(
            user=self.user,
            name="Fail Handler",
            scenario_id="basic",
            total_runs=1,
            max_parallel_runs=1,
            status=ExperimentStatus.RUNNING.value,
        )
        from django.utils import timezone

        exp.started_at = timezone.now()
        exp.save(update_fields=["started_at"])

        run = ExperimentRun.objects.create(
            experiment=exp,
            run_number=1,
            status=RunStatus.PROVISIONING.value,
        )

        process_event(
            {
                "event_type": "experiment.run.failed",
                "experiment_id": exp.pk,
                "run_id": run.pk,
                "error_message": "SSM timeout",
            }
        )

        run.refresh_from_db()
        assert run.status == RunStatus.FAILED.value
        assert run.error_message == "SSM timeout"
