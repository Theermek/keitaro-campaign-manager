import os
import tempfile
from pathlib import Path

# Must run before the app is imported: env vars take priority over .env,
# so tests never see the real Keitaro URL or API key.
_tmp = Path(tempfile.mkdtemp())
os.environ.update(
    KEITARO_API_URL="https://kt.test/admin_api/v1",
    KEITARO_API_KEY="test-key",
    KEITARO_TIMEOUT="1",
    CAMPAIGN_PREFIX="test_akella_",
    KEITARO_DOMAIN="tracker.example",
    KEITARO_GROUP="FORTESTS",
    KEITARO_SOURCE="FORTESTS",
    DATABASE_URL=f"sqlite:///{_tmp / 'test.db'}",
)

import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import OperationLog, StreamOffer  # noqa: E402
from app.services import catalog  # noqa: E402
from tests.fake_keitaro import FakeKeitaro  # noqa: E402

Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def _clean_state():
    catalog._offers.clear()
    catalog._reference.clear()
    with SessionLocal() as session:
        session.query(StreamOffer).delete()
        session.query(OperationLog).delete()
        session.commit()
    yield


@pytest.fixture
def kt():
    """Stateful fake Keitaro. Any request to another host fails the test."""
    fake = FakeKeitaro()
    with respx.mock(assert_all_called=False) as router:
        router.route(host="kt.test").mock(side_effect=fake.handle)
        yield fake


@pytest.fixture
def client(kt):
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
