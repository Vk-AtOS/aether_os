"""Fallback service layer generator — split from crud_generator.py to keep it under 600 lines.

Provides _fallback_service_layer for generating bare service stubs when the IR fast-path
is unavailable.

Note on generated imports: each method stubs uses `from models import <Name>` inside a
try block.  This is intentional — the generated service files are placed in src/ alongside
models.py, so the import resolves correctly at runtime in the generated project.
"""
from __future__ import annotations

import logging

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
            "    @staticmethod",
            "    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Any]:",
            "        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).offset(skip).limit(limit))",
            "            return list(result.scalars().all())",
            "        except Exception as _e:",
            f"            _logger.warning('{name}Service.get_all failed: %s', _e)",
            "            return []",
            "",
            "    @staticmethod",
            "    async def get_by_id(db: AsyncSession, id: int) -> Optional[Any]:",
            "        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            "            return result.scalar_one_or_none()",
            "        except Exception as _e:",
            f"            _logger.warning('{name}Service.get_by_id failed: %s', _e)",
            "            return None",
            "",
            "    @staticmethod",
            "    async def create(db: AsyncSession, data: Dict[str, Any]) -> Optional[Any]:",
            "        try:",
            f"            from models import {name}",
            f"            obj = {name}(**data)",
            "            db.add(obj)",
            "            await db.flush()",
            "            await db.refresh(obj)",
            "            return obj",
            "        except Exception as _e:",
            f"            _logger.warning('{name}Service.create failed: %s', _e)",
            "            return None",
            "",
            "    @staticmethod",
            "    async def update(db: AsyncSession, id: int, data: Dict[str, Any]) -> Optional[Any]:",
            "        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            "            obj = result.scalar_one_or_none()",
            "            if obj is None:",
            "                return None",
            "            for k, v in data.items():",
            "                setattr(obj, k, v)",
            "            await db.flush()",
            "            await db.refresh(obj)",
            "            return obj",
            "        except Exception as _e:",
            f"            _logger.warning('{name}Service.update failed: %s', _e)",
            "            return None",
            "",
            "    @staticmethod",
            "    async def delete(db: AsyncSession, id: int) -> bool:",
            "        try:",
            f"            from models import {name}",
            f"            result = await db.execute(select({name}).where({name}.id == id))",
            "            obj = result.scalar_one_or_none()",
            "            if obj is None:",
            "                return False",
            "            await db.delete(obj)",
            "            return True",
            "        except Exception as _e:",
            f"            _logger.warning('{name}Service.delete failed: %s', _e)",
            "            return False",
            "",
        ]
    return "\n".join(lines)
