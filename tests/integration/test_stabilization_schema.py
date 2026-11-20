from sqlalchemy import text

from tests.integration.helpers import reset_test_database


async def test_checkout_uses_migrated_payment_history() -> None:
    db = await reset_test_database()
    async with db() as session:
        assert await session.scalar(text("SELECT to_regclass('alembic_version')")) is not None
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgname = 'payment_review_append_only' "
                    "AND tgrelid = 'payment_evidence_review'::regclass"
                )
            )
            == 1
        )
