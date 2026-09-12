"""create_core_domain_schema

Revision ID: cd73103ae9e0
Revises:
Create Date: 2026-09-12 05:40:47.992707
"""

from alembic import op
import sqlalchemy as sa

from app.models.base import GUID, PortableJSON


revision = "cd73103ae9e0"
down_revision = None
branch_labels = None
depends_on = None

APP_TABLES = (
    "cars",
    "conversation_sessions",
    "chat_messages",
    "recommendation_snapshots",
    "recommendation_snapshot_items",
    "test_drive_requests",
    "sales_leads",
    "knowledge_documents",
)


def _enable_rls_and_revoke_data_api(table_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY'))
    for role_name in ("anon", "authenticated"):
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                        EXECUTE 'REVOKE ALL ON TABLE public."{table_name}" FROM {role_name}';
                    END IF;
                END
                $$;
                """
            )
        )


def upgrade():
    op.create_table(
        "cars",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=20), nullable=False),
        sa.Column("price_egp", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("body_type", sa.String(length=50), nullable=True),
        sa.Column("transmission", sa.String(length=50), nullable=True),
        sa.Column("fuel_type", sa.String(length=50), nullable=True),
        sa.Column("mileage_km", sa.BigInteger(), nullable=True),
        sa.Column("engine_capacity_cc", sa.Integer(), nullable=True),
        sa.Column("horsepower", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("powertrain_type", sa.String(length=50), nullable=True),
        sa.Column("trim", sa.String(length=100), nullable=True),
        sa.Column("color", sa.String(length=50), nullable=True),
        sa.Column("location", sa.String(length=100), nullable=True),
        sa.Column("vin", sa.String(length=100), nullable=True),
        sa.Column("stock_number", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_quality_status", sa.String(length=50), nullable=True),
        sa.Column("data_quality_metadata", PortableJSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(trim(brand)) > 0", name="ck_cars_car_brand_not_blank_check"),
        sa.CheckConstraint("length(trim(model)) > 0", name="ck_cars_car_model_not_blank_check"),
        sa.CheckConstraint("condition IN ('new', 'used')", name="ck_cars_car_condition_check"),
        sa.CheckConstraint("price_egp >= 0", name="ck_cars_car_price_non_negative_check"),
        sa.CheckConstraint(
            "mileage_km IS NULL OR mileage_km >= 0",
            name="ck_cars_car_mileage_non_negative_check",
        ),
        sa.CheckConstraint("year >= 1900", name="ck_cars_car_year_minimum_check"),
        sa.CheckConstraint(
            "engine_capacity_cc IS NULL OR engine_capacity_cc > 0",
            name="ck_cars_car_engine_capacity_positive_check",
        ),
        sa.CheckConstraint(
            "horsepower IS NULL OR horsepower >= 0",
            name="ck_cars_car_horsepower_non_negative_check",
        ),
        sa.CheckConstraint("length(trim(source)) > 0", name="ck_cars_car_source_not_blank_check"),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0",
            name="ck_cars_car_source_id_not_blank_check",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cars"),
        sa.UniqueConstraint("source", "source_id", name="uq_cars_source_source_id"),
    )
    op.create_index("ix_cars_active", "cars", ["active"], unique=False)
    op.create_index("ix_cars_condition", "cars", ["condition"], unique=False)
    op.create_index("ix_cars_price_egp", "cars", ["price_egp"], unique=False)
    op.create_index("ix_cars_brand", "cars", ["brand"], unique=False)
    op.create_index("ix_cars_model", "cars", ["model"], unique=False)
    op.create_index("ix_cars_brand_model", "cars", ["brand", "model"], unique=False)
    op.create_index("ix_cars_year", "cars", ["year"], unique=False)
    op.create_index("ix_cars_body_type", "cars", ["body_type"], unique=False)
    op.create_index("ix_cars_transmission", "cars", ["transmission"], unique=False)
    op.create_index("ix_cars_fuel_type", "cars", ["fuel_type"], unique=False)
    op.create_index(
        "ix_cars_active_condition_price",
        "cars",
        ["active", "condition", "price_egp"],
        unique=False,
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_knowledge_documents_knowledge_document_title_not_blank_check",
        ),
        sa.CheckConstraint(
            "length(trim(category)) > 0",
            name="ck_knowledge_documents_knowledge_document_category_not_blank_check",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_knowledge_documents_knowledge_document_content_not_blank_check",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_documents"),
    )
    op.create_index(
        "ix_knowledge_documents_category",
        "knowledge_documents",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_documents_active",
        "knowledge_documents",
        ["active"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_documents_category_active",
        "knowledge_documents",
        ["category", "active"],
        unique=False,
    )

    op.create_table(
        "conversation_sessions",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("preferences", PortableJSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("selected_car_id", sa.Integer(), nullable=True),
        sa.Column("active_recommendation_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("pending_action", PortableJSON(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_conversation_sessions_conversation_session_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["selected_car_id"],
            ["cars.id"],
            name="fk_conversation_sessions_selected_car_id_cars",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_sessions"),
    )
    op.create_index(
        "ix_conversation_sessions_status",
        "conversation_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_sessions_selected_car_id",
        "conversation_sessions",
        ["selected_car_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_sessions_active_recommendation_snapshot_id",
        "conversation_sessions",
        ["active_recommendation_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", GUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="ck_chat_messages_chat_message_role_check",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_chat_messages_chat_message_content_not_blank_check",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name="fk_chat_messages_session_id_conversation_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"], unique=False)
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "recommendation_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", GUID(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("criteria", PortableJSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "sequence_no > 0",
            name="ck_recommendation_snapshots_rec_snapshot_sequence_no_check",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'invalidated')",
            name="ck_recommendation_snapshots_rec_snapshot_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name="fk_recommendation_snapshots_session_id_conv_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendation_snapshots"),
        sa.UniqueConstraint(
            "session_id",
            "sequence_no",
            name="uq_rec_snapshots_session_sequence",
        ),
    )
    op.create_index(
        "ix_rec_snapshots_session_id",
        "recommendation_snapshots",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_rec_snapshots_session_sequence",
        "recommendation_snapshots",
        ["session_id", "sequence_no"],
        unique=False,
    )
    op.create_index(
        "ix_rec_snapshots_session_status",
        "recommendation_snapshots",
        ["session_id", "status"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_conversation_sessions_active_rec_snapshot",
        "conversation_sessions",
        "recommendation_snapshots",
        ["active_recommendation_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "recommendation_snapshot_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("car_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position > 0",
            name="ck_recommendation_snapshot_items_rec_snapshot_item_position_check",
        ),
        sa.ForeignKeyConstraint(
            ["car_id"],
            ["cars.id"],
            name="fk_rec_snapshot_items_car_id_cars",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["recommendation_snapshots.id"],
            name="fk_rec_snapshot_items_snapshot_id_rec_snapshots",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendation_snapshot_items"),
        sa.UniqueConstraint(
            "snapshot_id",
            "car_id",
            name="uq_rec_snapshot_items_snapshot_car",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "position",
            name="uq_rec_snapshot_items_snapshot_position",
        ),
    )
    op.create_index(
        "ix_rec_snapshot_items_snapshot_id",
        "recommendation_snapshot_items",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_rec_snapshot_items_car_id",
        "recommendation_snapshot_items",
        ["car_id"],
        unique=False,
    )

    op.create_table(
        "test_drive_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", GUID(), nullable=False),
        sa.Column("car_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("preferred_date", sa.Date(), nullable=False),
        sa.Column("preferred_time", sa.Time(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="NEW", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('NEW', 'CONFIRMED', 'COMPLETED', 'CANCELLED')",
            name="ck_test_drive_requests_test_drive_status_check",
        ),
        sa.CheckConstraint(
            "length(trim(customer_name)) > 0",
            name="ck_test_drive_requests_test_drive_customer_name_not_blank_check",
        ),
        sa.CheckConstraint(
            "length(trim(phone)) > 0",
            name="ck_test_drive_requests_test_drive_phone_not_blank_check",
        ),
        sa.ForeignKeyConstraint(
            ["car_id"],
            ["cars.id"],
            name="fk_test_drive_requests_car_id_cars",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name="fk_test_drive_requests_session_id_conv_sessions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_test_drive_requests"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_test_drive_requests_idempotency_key",
        ),
    )
    op.create_index(
        "ix_test_drive_requests_session_id",
        "test_drive_requests",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_drive_requests_car_id",
        "test_drive_requests",
        ["car_id"],
        unique=False,
    )
    op.create_index(
        "ix_test_drive_requests_status",
        "test_drive_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_test_drive_requests_session_status",
        "test_drive_requests",
        ["session_id", "status"],
        unique=False,
    )

    op.create_table(
        "sales_leads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", GUID(), nullable=False),
        sa.Column("car_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="NEW", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'CLOSED_WON', 'CLOSED_LOST')",
            name="ck_sales_leads_sales_lead_status_check",
        ),
        sa.CheckConstraint(
            "length(trim(customer_name)) > 0",
            name="ck_sales_leads_sales_lead_customer_name_not_blank_check",
        ),
        sa.CheckConstraint(
            "length(trim(phone)) > 0",
            name="ck_sales_leads_sales_lead_phone_not_blank_check",
        ),
        sa.ForeignKeyConstraint(
            ["car_id"],
            ["cars.id"],
            name="fk_sales_leads_car_id_cars",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name="fk_sales_leads_session_id_conv_sessions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sales_leads"),
        sa.UniqueConstraint("idempotency_key", name="uq_sales_leads_idempotency_key"),
    )
    op.create_index("ix_sales_leads_session_id", "sales_leads", ["session_id"], unique=False)
    op.create_index("ix_sales_leads_car_id", "sales_leads", ["car_id"], unique=False)
    op.create_index("ix_sales_leads_status", "sales_leads", ["status"], unique=False)
    op.create_index(
        "ix_sales_leads_session_status",
        "sales_leads",
        ["session_id", "status"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION public.enforce_active_snapshot_session()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY INVOKER
            SET search_path = public
            AS $$
            BEGIN
                IF NEW.active_recommendation_snapshot_id IS NOT NULL
                   AND NOT EXISTS (
                        SELECT 1
                        FROM public.recommendation_snapshots AS rs
                        WHERE rs.id = NEW.active_recommendation_snapshot_id
                          AND rs.session_id = NEW.id
                   )
                THEN
                    RAISE EXCEPTION
                        'active recommendation snapshot must belong to the same conversation session'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_conversation_active_snapshot_session
            AFTER INSERT OR UPDATE OF active_recommendation_snapshot_id
            ON public.conversation_sessions
            DEFERRABLE INITIALLY IMMEDIATE
            FOR EACH ROW
            EXECUTE FUNCTION public.enforce_active_snapshot_session();
            """
        )
    )

    for table_name in APP_TABLES:
        _enable_rls_and_revoke_data_api(table_name)

    op.execute(sa.text("ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY"))
    for role_name in ("anon", "authenticated"):
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                        EXECUTE 'REVOKE ALL ON TABLE public.alembic_version FROM {role_name}';
                    END IF;
                END
                $$;
                """
            )
        )

    op.execute(
        sa.text(
            "REVOKE ALL ON FUNCTION public.enforce_active_snapshot_session() FROM PUBLIC"
        )
    )
    for role_name in ("anon", "authenticated"):
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                        EXECUTE
                            'REVOKE ALL ON FUNCTION public.enforce_active_snapshot_session() '
                            'FROM {role_name}';
                    END IF;
                END
                $$;
                """
            )
        )


def downgrade():
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_conversation_active_snapshot_session "
            "ON public.conversation_sessions"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS public.enforce_active_snapshot_session()"))

    op.drop_constraint(
        "fk_conversation_sessions_active_rec_snapshot",
        "conversation_sessions",
        type_="foreignkey",
    )

    op.drop_table("sales_leads")
    op.drop_table("test_drive_requests")
    op.drop_table("recommendation_snapshot_items")
    op.drop_table("recommendation_snapshots")
    op.drop_table("chat_messages")
    op.drop_table("conversation_sessions")
    op.drop_table("knowledge_documents")
    op.drop_table("cars")
