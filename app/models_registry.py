"""Central SQLAlchemy model registry.

Every new SQLAlchemy model module MUST be imported here. Entrypoints and scripts
import this registry before using Base.metadata or creating database sessions so
foreign keys can resolve against the complete metadata graph.
"""

from app.ai import models as ai_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.channel import models as channel_models  # noqa: F401
from app.conversation import models as conversation_models  # noqa: F401
from app.customer import models as customer_models  # noqa: F401
from app.handoff import models as handoff_models  # noqa: F401
