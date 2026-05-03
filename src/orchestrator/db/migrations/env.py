from logging.config import fileConfig
import asyncio

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the Base from ORM models
from orchestrator.db.orm.base import Base

# Import all models so Alembic can detect them
import orchestrator.db.orm.models as _models  # noqa: F401
from orchestrator.runners import AgentConfigModel as _AgentConfigModel  # noqa: F401

_models_loaded = _models  # ensure pyright sees the import as used
_agent_model_loaded = _AgentConfigModel  # ensure pyright sees the import as used

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_configure_and_migrate(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # Required for SQLite
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    If a connection is provided via ``config.attributes["connection"]``
    (programmatic invocation from ``init_db``), use it directly.
    Otherwise create an async engine from the ini-file settings (CLI usage).
    """
    existing_connection = config.attributes.get("connection", None)
    if existing_connection is not None:
        _do_configure_and_migrate(existing_connection)
        return

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async def do_run_migrations() -> None:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_configure_and_migrate)
        await connectable.dispose()

    asyncio.run(do_run_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
