"""Drop the 'google' / 'google_calendar' enum members and purge related rows.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade():
    # 1. Purge data that references removed enum members.
    op.execute("UPDATE events SET source = 'local' WHERE source = 'google'")
    op.execute("DELETE FROM integrations WHERE provider = 'google_calendar'")
    op.execute(
        "DELETE FROM biometrics_snapshots WHERE provider = 'google_calendar'"
    )

    op.execute("ALTER TYPE event_source RENAME TO event_source_old")
    op.execute("CREATE TYPE event_source AS ENUM ('yandex', 'local')")
    op.execute(
        "ALTER TABLE events "
        "ALTER COLUMN source DROP DEFAULT, "
        "ALTER COLUMN source TYPE event_source USING source::text::event_source, "
        "ALTER COLUMN source SET DEFAULT 'local'"
    )
    op.execute("DROP TYPE event_source_old")

    # 3. Shrink integration_provider: drop 'google_calendar'.
    op.execute("ALTER TYPE integration_provider RENAME TO integration_provider_old")
    op.execute(
        "CREATE TYPE integration_provider AS ENUM ('yandex_calendar', 'whoop')"
    )
    op.execute(
        "ALTER TABLE integrations "
        "ALTER COLUMN provider TYPE integration_provider "
        "USING provider::text::integration_provider"
    )
    op.execute(
        "ALTER TABLE biometrics_snapshots "
        "ALTER COLUMN provider TYPE integration_provider "
        "USING provider::text::integration_provider"
    )
    op.execute("DROP TYPE integration_provider_old")

def downgrade():
    op.execute("ALTER TYPE event_source RENAME TO event_source_old")
    op.execute("CREATE TYPE event_source AS ENUM ('google', 'yandex', 'local')")
    op.execute(
        "ALTER TABLE events "
        "ALTER COLUMN source DROP DEFAULT, "
        "ALTER COLUMN source TYPE event_source USING source::text::event_source, "
        "ALTER COLUMN source SET DEFAULT 'local'"
    )
    op.execute("DROP TYPE event_source_old")

    op.execute("ALTER TYPE integration_provider RENAME TO integration_provider_old")
    op.execute(
        "CREATE TYPE integration_provider AS ENUM "
        "('google_calendar', 'yandex_calendar', 'whoop')"
    )
    op.execute(
        "ALTER TABLE integrations "
        "ALTER COLUMN provider TYPE integration_provider "
        "USING provider::text::integration_provider"
    )
    op.execute(
        "ALTER TABLE biometrics_snapshots "
        "ALTER COLUMN provider TYPE integration_provider "
        "USING provider::text::integration_provider"
    )
    op.execute("DROP TYPE integration_provider_old")
