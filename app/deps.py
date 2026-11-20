import json
from collections.abc import Iterator

from app.config import get_settings
from app.db import SessionLocal
from app.keitaro.client import KeitaroClient, WriteRecord
from app.models import OperationLog


def audit_to_db(record: WriteRecord) -> None:
    # Own session: the audit row must be saved even if the caller rolls back
    with SessionLocal() as session:
        session.add(
            OperationLog(
                method=record.method,
                path=record.path,
                campaign_id=record.campaign_id,
                status_code=record.status_code,
                request_body=json.dumps(record.body, ensure_ascii=False),
                error=record.error,
            )
        )
        session.commit()


def get_keitaro() -> Iterator[KeitaroClient]:
    client = KeitaroClient(get_settings(), audit=audit_to_db)
    try:
        yield client
    finally:
        client.close()
