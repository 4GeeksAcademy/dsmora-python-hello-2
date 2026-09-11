import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from data.pipelines import pipeline


def run_task(task, *args):
    with patch.object(pipeline, "get_run_logger", return_value=Mock()):
        return task.fn(*args)


class PipelineTasksTests(unittest.TestCase):
    def test_extract_events_reads_raw_records_without_transforming(self):
        raw_event = {
            "event_id": "raw-1",
            "user_id": 17,
            "timestamp": "2024-01-01T10:00:00Z",
            "action": "PURCHASE",
            "amount": "12.50",
            "extra": {"source": "telemetry"},
        }
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "events.jsonl"
            source_path.write_text(json.dumps(raw_event) + "\n", encoding="utf-8")

            events = run_task(pipeline.extract_events, source_path)

        self.assertEqual(events, [raw_event])

    def test_transform_events_returns_canonical_events_and_removes_duplicates(self):
        events = run_task(pipeline.transform_events, 
            [
                {
                    "event_id": "evt-1",
                    "user_id": 7,
                    "timestamp": "2024-01-02T12:00:00Z",
                    "action": " PURCHASE ",
                    "amount": "12.50",
                },
                {
                    "event_id": "evt-1",
                    "user_id": 7,
                    "timestamp": "2024-01-02T12:00:00Z",
                    "action": "PURCHASE",
                    "amount": "12.50",
                },
                {"user_id": 8, "action": "purchase", "amount": 3},
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0],
            {
                "event_id": "evt-1",
                "user_id": "7",
                "timestamp": "2024-01-02T12:00:00Z",
                "action": "purchase",
                "amount": 12.5,
            },
        )
        self.assertEqual(
            set(events[0]), {"event_id", "user_id", "timestamp", "action", "amount"}
        )

    def test_transform_product_events_adapts_different_input_schema(self):
        events = run_task(pipeline.transform_product_events, 
            [
                {
                    "product_event_id": "product-1",
                    "customer": 21,
                    "occurred_at": "2024-02-03T09:30:00Z",
                    "event_type": "ORDER",
                    "price": "20.00",
                },
                {
                    "product_event_id": "product-2",
                    "customer": 22,
                    "occurred_at": "2024-02-03T09:31:00Z",
                    "event_type": "FAIL",
                    "price": 0,
                },
            ]
        )

        self.assertEqual(
            events,
            [
                {
                    "event_id": "product-1",
                    "user_id": "21",
                    "timestamp": "2024-02-03T09:30:00Z",
                    "action": "purchase",
                    "amount": 20.0,
                },
                {
                    "event_id": "product-2",
                    "user_id": "22",
                    "timestamp": "2024-02-03T09:31:00Z",
                    "action": "error",
                    "amount": None,
                },
            ],
        )
        for event in events:
            self.assertEqual(
                set(event), {"event_id", "user_id", "timestamp", "action", "amount"}
            )

    def test_calculate_kpis_returns_expected_business_metrics(self):
        events = [
            {
                "event_id": "1",
                "user_id": "a",
                "timestamp": "2024-01-01T10:00:00Z",
                "action": "purchase",
                "amount": 12.5,
            },
            {
                "event_id": "2",
                "user_id": "a",
                "timestamp": "2024-01-01T11:00:00Z",
                "action": "page_view",
                "amount": 0.0,
            },
            {
                "event_id": "3",
                "user_id": "b",
                "timestamp": "2024-01-01T12:00:00Z",
                "action": "error",
                "amount": 0.0,
            },
        ]

        kpis = pipeline.calculate_kpis.fn(events)

        self.assertEqual(kpis["total_events"], 3)
        self.assertEqual(kpis["unique_users"], 2)
        self.assertEqual(kpis["purchases"], 1)
        self.assertEqual(kpis["revenue"], 12.5)
        self.assertEqual(kpis["conversion_rate"], 0.5)
        self.assertEqual(kpis["error_rate"], round(1 / 3, 4))
        self.assertEqual(kpis["window_start"], "2024-01-01T10:00:00Z")
        self.assertEqual(kpis["window_end"], "2024-01-01T12:00:00Z")

    def test_load_kpis_is_idempotent_and_writes_latest_result(self):
        kpis = {
            "total_events": 1,
            "unique_users": 1,
            "purchases": 1,
            "revenue": 12.5,
            "conversion_rate": 1.0,
            "error_rate": 0.0,
            "window_start": "2024-01-01T00:00:00Z",
            "window_end": "2024-01-01T01:00:00Z",
        }
        with tempfile.TemporaryDirectory() as directory:
            reporting_dir = Path(directory)
            with patch.object(pipeline, "REPORTING_DIR", reporting_dir):
                run_task(pipeline.load_kpis, kpis)
                run_task(pipeline.load_kpis, kpis)

            with sqlite3.connect(reporting_dir / "business_kpis.sqlite") as connection:
                count = connection.execute("SELECT COUNT(*) FROM reporting_kpis").fetchone()[0]
            latest = json.loads(
                (reporting_dir / "latest_kpis.json").read_text(encoding="utf-8")
            )

        self.assertEqual(count, 1)
        self.assertEqual(latest, kpis)


class PipelineFlowTests(unittest.TestCase):
    def test_subflows_and_main_flow_combine_sources_and_write_outputs(self):
        telemetry_event = {
            "event_id": "telemetry-1",
            "user_id": "customer-1",
            "timestamp": "2024-01-01T10:00:00Z",
            "action": "page_view",
            "amount": 0,
        }
        product_event = {
            "product_event_id": "product-1",
            "customer": "customer-2",
            "occurred_at": "2024-01-01T11:00:00Z",
            "event_type": "ORDER",
            "price": 20,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web_path = root / "telemetry.jsonl"
            product_web_path = root / "products.jsonl"
            web_path.write_text(json.dumps(telemetry_event) + "\n", encoding="utf-8")
            product_web_path.write_text(
                json.dumps(product_event) + "\n", encoding="utf-8"
            )
            reporting_dir = root / "reporting"
            processed_dir = root / "processed"

            with patch.object(pipeline, "REPORTING_DIR", reporting_dir), patch.object(
                pipeline, "PROCESSED_DIR", processed_dir
            ):
                web_subflow_result = pipeline.web_telemetry_subflow(str(web_path))
                product_subflow_result = pipeline.product_telemetry_subflow(str(product_web_path))
                self.assertEqual(len(web_subflow_result["events"]), 1)
                self.assertEqual(len(product_subflow_result["events"]), 1)

                kpis = pipeline.business_performance_pipeline(
                    source_path=str(web_path),
                    product_source_path=str(product_web_path),
                )

            self.assertEqual(kpis["total_events"], 2)
            self.assertEqual(kpis["unique_users"], 2)
            self.assertEqual(kpis["purchases"], 1)
            self.assertEqual(kpis["revenue"], 20.0)
            for filename in (
                "business_kpis.sqlite",
                "latest_kpis.json",
                "pipeline_runs.jsonl",
            ):
                self.assertTrue((reporting_dir / filename).exists(), filename)
            self.assertTrue((processed_dir / "eval_snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
