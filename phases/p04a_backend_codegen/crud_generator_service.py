"""Fallback service layer generator — split from crud_generator.py to keep it under 600 lines.

Provides _fallback_service_layer for generating bare service stubs when the IR fast-path
is unavailable.

Note on generated imports: each method stubs uses `from models import <Name>` inside a
try block.  This is intentional — the generated service files are placed in src/ alongside
models.py, so the import resolves correctly at runtime in the generated project.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fallback_service_layer(entities: list) -> str:
    """Generate bare service stubs for each entity using SQLAlchemy select/add/delete.

    Each stub uses try/except with logging so runtime errors are surfaced, not silenced.
    """
    lines = [
        "from __future__ import annotations",
        "from typing import Any, Dict, List, Optional",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "from sqlalchemy import select",
        "import logging",
        "",
        "_logger = logging.getLogger(__name__)",
        "",
    ]
    for ent in entities[:8]:
        name = ent.get("name", "Item")
        lines += [
            f"class {name}Service:",
            f"    @staticmethod",
            f"    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).offset(skip).limit(limit))",
            f"            return list(result.scalars().all())",
            f"        except Exception as _e:",
            f"            _logger.warning('{name}Service.get_all failed: %s', _e)",
            f"            return []",
            "",
            f"    @staticmethod",
            f"    async def get_by_id(db: AsyncSession, id: int) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            return result.scalar_one_or_none()",
            f"        except Exception as _e:",
            f"            _logger.warning('{name}Service.get_by_id failed: %s', _e)",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def create(db: AsyncSession, data: Dict[str, Any]) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            obj = {name}(**data)",
            f"            db.add(obj)",
            f"            await db.flush()",
            f"            await db.refresh(obj)",
            f"            return obj",
            f"        except Exception as _e:",
            f"            _logger.warning('{name}Service.create failed: %s', _e)",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def update(db: AsyncSession, id: int, data: Dict[str, Any]) -> Optional[Any]:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            obj = result.scalar_one_or_none()",
            f"            if obj is None:",
            f"                return None",
            f"            for k, v in data.items():",
            f"                setattr(obj, k, v)",
            f"            await db.flush()",
            f"            await db.refresh(obj)",
            f"            return obj",
            f"        except Exception as _e:",
            f"            _logger.warning('{name}Service.update failed: %s', _e)",
            f"            return None",
            "",
            f"    @staticmethod",
            f"    async def delete(db: AsyncSession, id: int) -> bool:",
            f"        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            f"            obj = result.scalar_one_or_none()",
            f"            if obj is None:",
            f"                return False",
            f"            await db.delete(obj)",
            f"            return True",
            f"        except Exception as _e:",
            f"            _logger.warning('{name}Service.delete failed: %s', _e)",
            f"            return False",
            "",
        ]
    return "\n".join(lines)
