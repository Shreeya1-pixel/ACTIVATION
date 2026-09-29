import copy
import unittest

from jsonschema.exceptions import ValidationError
from backend.validate_events import validate_events, validator

EVENT = {
    "schema_version": 1, "source_version": "phase1-0.1.0",
    "event_id": "12a72087-bb18-477e-bf65-1a203d3e6500",
    "captured_at": "2026-09-20T10:00:00Z", "processed_at": "2026-09-20T10:00:01Z",
    "source": "sample_browser", "action": "record_opened", "resource": "sample-client-page",
    "record_key": "sample:C001", "changed_fields": [], "outcome": "success", "synthetic": True,
}


class ContractTests(unittest.TestCase):
    def test_both_schemas_are_valid(self):
        for name in ("event", "runner-report"):
            validator(name)

    def test_minimized_event_is_valid(self):
        validate_events([EVENT])

    def test_raw_values_and_authority_cannot_be_added(self):
        for field in ("email", "value", "clipboard", "password", "approved", "permissions"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_events([dict(EVENT, **{field: "must not enter events"})])

    def test_invalid_time_key_and_source_are_rejected(self):
        for update in ({"event_id": "not-a-uuid"}, {"captured_at": "yesterday"},
                       {"captured_at": "2026-02-30T10:00:00Z"}, {"captured_at": "2026-09-20T10:00:00"}, {"record_key": "actual-client"},
                       {"source": "saved_file_comparison"}, {"changed_fields": ["Email"]}, {"synthetic": False}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                validate_events([dict(EVENT, **update)])

    def test_duplicate_event_cannot_count_twice(self):
        with self.assertRaises(ValueError):
            validate_events([EVENT, copy.deepcopy(EVENT)])

    def test_collection_is_bounded(self):
        for value in ({}, [EVENT] * 101):
            with self.assertRaises(ValueError):
                validate_events(value)

    def test_file_event_requires_actual_changed_fields(self):
        event = dict(EVENT, source="saved_file_comparison", action="spreadsheet_row_updated", resource="sample-tracking-file")
        with self.assertRaises(ValidationError):
            validate_events([event])
        validate_events([dict(event, changed_fields=["Status"])])

    def test_report_shape_binds_versions_and_cannot_pass_with_failed_checks(self):
        report = {"schema_version": 1, "job_id": EVENT["event_id"], "owner_id": "sample-owner",
                  "runner_id": "sample-runner", "policy_version": "fixture-v1", "connector_version": "fixture-v1",
                  "status": "passed", "issued_at": EVENT["captured_at"], "expires_at": "2026-09-21T10:00:00Z",
                  "checks": [{"id": "expected-output", "result": "pass"}], "signature_key_id": "sample-key",
                  "signature": "not-a-real-signature"}
        for field in ("artifact", "plan", "permissions", "input", "output", "runtime", "suite"):
            report[f"{field}_sha256"] = "a" * 64
        contract = validator("runner-report")
        contract.validate(report)  # Shape validity deliberately makes no authenticity/approval claim.
        for result in ("fail", "missing", "timeout"):
            with self.subTest(result=result), self.assertRaises(ValidationError):
                contract.validate(dict(report, checks=[{"id": "expected-output", "result": result}]))
        for field in ("plan_sha256", "permissions_sha256", "suite_sha256", "expires_at"):
            incomplete = dict(report)
            del incomplete[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                contract.validate(incomplete)


if __name__ == "__main__":
    unittest.main()
