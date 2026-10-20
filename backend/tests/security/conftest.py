from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.schema.cards import load_workspace_schema
from app.services.sqlguard import AllowedSchema


@pytest.fixture
def allowed(db: Session, demo_ws: str) -> AllowedSchema:
    return load_workspace_schema(db, demo_ws).allowed()


# A static copy of the demo schema for tests that don't need DuckDB (fast, used by hypothesis).
STATIC_SCHEMA = AllowedSchema.from_columns(
    {
        "transactions": (
            1096,
            [
                "txn_id", "txn_date", "account_id", "description", "merchant_id", "amount",
                "type", "payment_mode", "status", "notes",
            ],
        ),
        "accounts": (
            5,
            [
                "account_id", "account_name", "bank", "account_type", "opened_on",
                "opening_balance", "credit_limit", "active",
            ],
        ),
        "merchants": (33, ["merchant_id", "merchant_name", "category_id", "city", "upi_handle"]),
        "categories": (15, ["category_id", "category_name", "category_group", "is_essential"]),
        "budgets": (162, ["month", "category_id", "budget"]),
    }
)  # fmt: skip
