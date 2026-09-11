import pytest
from fastapi.testclient import TestClient

from open_document_intelligence.main import create_app


@pytest.fixture()
def client(tmp_path) -> TestClient:
    app = create_app(data_dir=tmp_path / "data")
    return TestClient(app)
