import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from telegram_locator import TelegramDocumentLocator


class TelegramLocatorTests(unittest.TestCase):
    def test_locator_rejects_missing_required_fields(self):
        locator = TelegramDocumentLocator()
        message = locator.create_message_for_request(
            {
                "message_id": 1,
                "channel_id": "chan",
                "filename": "track.wav",
                "file_size": 100,
                "type": "audio",
            }
        )

        self.assertIsNone(message)

    def test_locator_creates_message_for_valid_request(self):
        locator = TelegramDocumentLocator()
        message = locator.create_message_for_request(
            {
                "message_id": 1,
                "channel_id": "chan",
                "filename": "track.wav",
                "file_size": 100,
                "type": "audio",
                "mime_type": "audio/vnd.wave",
                "document_id": 10,
                "access_hash": 20,
                "file_reference": b"ref",
            }
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.media.document.id, 10)


if __name__ == "__main__":
    unittest.main()
