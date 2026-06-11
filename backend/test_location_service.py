import json
import tempfile
import unittest
from pathlib import Path

from backend.services.location_service import _resolve_location_data_path


class LocationServicePathTests(unittest.TestCase):
    def test_resolve_location_data_path_falls_back_to_cwd_repo_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            data_dir = repo_root / "backend" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            expected_path = data_dir / "locations.json"
            expected_path.write_text(
                json.dumps({"regions": [], "countries": []}),
                encoding="utf-8",
            )

            resolved = _resolve_location_data_path(
                anchor_path=Path("/backend/services/location_service.py"),
                cwd=repo_root,
            )

            self.assertEqual(resolved, expected_path)

    def test_resolve_location_data_path_supports_backend_container_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            backend_root = Path(tmp_dir)
            data_dir = backend_root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            expected_path = data_dir / "locations.json"
            expected_path.write_text(
                json.dumps({"regions": [], "countries": []}),
                encoding="utf-8",
            )

            resolved = _resolve_location_data_path(
                anchor_path=Path("/app/services/location_service.py"),
                cwd=backend_root,
            )

            self.assertEqual(resolved, expected_path)


if __name__ == "__main__":
    unittest.main()
