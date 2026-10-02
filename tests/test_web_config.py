import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from config import ConfigLoader
from web_config import ConfigValidationError, WebConfigService


def base_config_text(output_dir: Path) -> str:
    return "\n".join(
        [
            "# Base config comment",
            "telegram:",
            "  api_id: 123456",
            '  api_hash: "base-placeholder"',
            "  two_factor_auth: false",
            "channels:",
            "  - -1001234567890",
            '  - "@music"',
            "download:",
            f'  output_dir: "{output_dir.as_posix()}"',
            "  timeout_between_messages: 0.3",
            "  max_files_per_run: 100",
            "  concurrent_downloads: 5  # workers comment",
            "  max_queue_size: 100",
            "  rate_limit:",
            "    requests_per_second: 2",
            "    burst_size: 5",
            "naming:",
            '  template: "{original_name}__{message_id}"',
            '  date_format: "%Y%m%d_%H%M%S"',
            "normalize_track_names: false",
            "filters:",
            '  file_types: ["audio", "document"]',
            '  formats: [".flac", ".mp3"]',
            "  size:",
            "    min_mb: 1",
            "    max_mb: 500",
            "  duration:",
            "    min_sec: null",
            "    max_sec: null",
            "  date:",
            '    from: "2026-01-01"  # date comment',
            "    to: null",
            "logging:",
            '  level: "INFO"',
            "  console: true",
            "",
        ]
    )


class WebConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.base_path = root / "config.yaml"
        self.local_path = root / "local_config.yaml"
        self.base_path.write_text(base_config_text(root / "out"), encoding="utf-8")
        self.local_path.write_text(
            yaml.safe_dump(
                {
                    "telegram": {"api_hash": "secret-hash-abcd", "extra_key": "keep"},
                    "custom_section": {"value": 1},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.service = WebConfigService(str(self.base_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def load_local(self) -> dict:
        return yaml.safe_load(self.local_path.read_text(encoding="utf-8"))

    def test_read_masks_api_hash(self) -> None:
        result = self.service.read()

        telegram = result["config"]["telegram"]
        self.assertNotIn("api_hash", telegram)
        self.assertTrue(telegram["api_hash_set"])
        self.assertEqual(telegram["api_hash_hint"], "****abcd")
        self.assertNotIn("secret-hash-abcd", repr(result))
        self.assertTrue(result["local_exists"])
        self.assertEqual(result["local_path"], str(self.local_path))
        self.assertEqual(result["config"]["filters"]["date"]["from"], "2026-01-01")

    def test_partial_update_writes_only_differing_keys(self) -> None:
        result = self.service.update(
            {
                "download": {"concurrent_downloads": 8, "max_queue_size": 100},
                "filters": {"formats": ["FLAC", ".Wav"]},
                "logging": {"level": "debug"},
            }
        )

        local = self.load_local()
        self.assertEqual(local["download"], {"concurrent_downloads": 8})
        self.assertEqual(local["filters"], {"formats": [".flac", ".wav"]})
        self.assertEqual(local["logging"], {"level": "DEBUG"})
        self.assertEqual(local["telegram"]["extra_key"], "keep")
        self.assertEqual(local["custom_section"], {"value": 1})
        self.assertEqual(result["config"]["download"]["concurrent_downloads"], 8)
        self.assertEqual(result["config"]["logging"]["level"], "DEBUG")

    def test_value_equal_to_base_removes_override(self) -> None:
        self.service.update({"download": {"concurrent_downloads": 8}})
        self.service.update({"download": {"concurrent_downloads": 5}})

        self.assertNotIn("download", self.load_local())

    def test_empty_api_hash_keeps_existing_value(self) -> None:
        self.service.update({"telegram": {"api_hash": "", "api_id": "654321"}})

        local = self.load_local()
        self.assertEqual(local["telegram"]["api_hash"], "secret-hash-abcd")
        self.assertEqual(local["telegram"]["api_id"], 654321)
        self.assertEqual(ConfigLoader(str(self.base_path)).get_api_hash(), "secret-hash-abcd")

    def test_date_from_is_written_to_base_not_local(self) -> None:
        self.local_path.write_text(
            yaml.safe_dump({"filters": {"date": {"from": "2025-01-01"}}}),
            encoding="utf-8",
        )

        result = self.service.update({"filters": {"date": {"from": "2026-03-04"}}})

        self.assertFalse(self.local_path.exists() and self.load_local())
        base_text = self.base_path.read_text(encoding="utf-8")
        self.assertIn('from: "2026-03-04"  # date comment', base_text)
        self.assertIn("# Base config comment", base_text)
        self.assertIn("concurrent_downloads: 5  # workers comment", base_text)
        self.assertEqual(result["config"]["filters"]["date"]["from"], "2026-03-04")

    def test_validation_reports_all_errors_and_writes_nothing(self) -> None:
        base_before = self.base_path.read_bytes()
        local_before = self.local_path.read_bytes()

        with self.assertRaises(ConfigValidationError) as context:
            self.service.update(
                {
                    "download": {"concurrent_downloads": 50, "unknown": 1},
                    "channels": ["@a", "@a"],
                    "filters": {"size": {"min_mb": 10, "max_mb": True}},
                    "logging": {"level": "LOUD"},
                }
            )

        errors = context.exception.errors
        self.assertGreaterEqual(len(errors), 5)
        joined = "\n".join(errors)
        for field in (
            "download.concurrent_downloads",
            "download.unknown",
            "channels[1]",
            "filters.size.max_mb",
            "logging.level",
        ):
            self.assertIn(field, joined)
        self.assertEqual(self.base_path.read_bytes(), base_before)
        self.assertEqual(self.local_path.read_bytes(), local_before)

    def test_reload_failure_restores_both_files(self) -> None:
        base_before = self.base_path.read_bytes()
        local_before = self.local_path.read_bytes()
        initial_loader = ConfigLoader(str(self.base_path))

        with mock.patch(
            "web_config.ConfigLoader",
            side_effect=[initial_loader, RuntimeError("reload failed")],
        ):
            with self.assertRaises(ConfigValidationError) as context:
                self.service.update(
                    {
                        "download": {"concurrent_downloads": 9},
                        "filters": {"date": {"from": "2026-05-05"}},
                    }
                )

        self.assertEqual(context.exception.errors, ["reload failed"])
        self.assertEqual(self.base_path.read_bytes(), base_before)
        self.assertEqual(self.local_path.read_bytes(), local_before)

    def test_reload_failure_removes_new_local_file(self) -> None:
        self.local_path.unlink()
        initial_loader = ConfigLoader(str(self.base_path))

        with mock.patch(
            "web_config.ConfigLoader",
            side_effect=[initial_loader, RuntimeError("reload failed")],
        ):
            with self.assertRaises(ConfigValidationError):
                self.service.update({"download": {"concurrent_downloads": 9}})

        self.assertFalse(self.local_path.exists())

    def test_update_date_from_behavior_unchanged(self) -> None:
        loader = ConfigLoader(str(self.base_path))

        returned = loader.update_date_from()

        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(returned, today)
        self.assertIn(
            f'from: "{today}"  # date comment',
            self.base_path.read_text(encoding="utf-8"),
        )
        self.assertEqual(loader._config["filters"]["date"]["from"], today)

        loader.set_date_from(None)
        self.assertIn("from: null  # date comment", self.base_path.read_text(encoding="utf-8"))
        self.assertIsNone(ConfigLoader(str(self.base_path)).get_date_filter()["from"])


if __name__ == "__main__":
    unittest.main()
