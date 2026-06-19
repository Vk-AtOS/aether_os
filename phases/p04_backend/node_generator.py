"""
Node/TypeScript + Fastify REST API generator for AetherOS P04 backend phase.

Called when build_profile.backend_lang == "typescript". Generates a complete
TypeScript/Fastify project from domain IR entities.

Output layout (under output_dir/backend/):
  src/index.ts
  src/routes/<Entity>.ts
  src/models/<Entity>.ts
  src/db.ts
  package.json
  tsconfig.json
  Dockerfile
  .env.example
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _to_pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def _to_camel(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return parts[0].lower() + "".join(w.capitalize() for w in parts[1:])


def generate_package_json(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    return f"""{{
  "name": "{slug}",
  "version": "1.0.0",
  "scripts": {{
    "dev": "ts-node-dev src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js"
  }},
  "dependencies": {{
    "fastify": "^4.25.2",
    "@fastify/cors": "^9.0.1",
    "drizzle-orm": "^0.29.3",
    "postgres": "^3.4.3",
    "dotenv": "^16.3.1",
    "zod": "^3.22.4",
    "jsonwebtoken": "^9.0.2"
  }},
  "devDependencies": {{
    "typescript": "^5.3.3",
    "@types/node": "^20.10.0",
    "@types/jsonwebtoken": "^9.0.5",
    "ts-node-dev": "^2.0.0"
  }}
}}
"""


def generate_tsconfig() -> str:
    return """{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
"""


def generate_ts_db() -> str:
    return """import { drizzle } from 'drizzle-orm/postgres-js';
import postgres from 'postgres';
import * as dotenv from 'dotenv';

dotenv.config();

const connectionString = process.env.DATABASE_URL!;
const client = postgres(connectionString);
export const db = drizzle(client);
"""


def generate_ts_model(entity: Dict[str, Any]) -> str:
    table = entity.get("table", "item")
    pascal = _to_pascal(table)
    fields = entity.get("fields", [])

    ts_fields = ["  id: number;", "  createdAt: Date;", "  updatedAt: Date;"]
    for f in fields:
        fname = f.get("name", "field")
        ftype = f.get("type", "string").lower()
        ts_type = {
            "string": "string", "text": "string", "int": "number",
            "integer": "number", "float": "number", "bool": "boolean",
            "boolean": "boolean", "datetime": "Date", "date": "Date",
            "fk": "number",
        }.get(ftype, "string")
        ts_fields.append(f"  {_to_camel(fname)}: {ts_type};")

    fields_str = "\n".join(ts_fields)
    return f"""export interface {pascal} {{
{fields_str}
}}

export type Create{pascal}Input = Omit<{pascal}, 'id' | 'createdAt' | 'updatedAt'>;
"""


def generate_ts_route(entity: Dict[str, Any]) -> str:
    table = entity.get("table", "item")
    pascal = _to_pascal(table)

    return f"""import {{ FastifyInstance }} from 'fastify';
import {{ db }} from '../db';

export async function {_to_camel(table)}Routes(fastify: FastifyInstance) {{
  // GET /{table}
  fastify.get('/{table}', async (_req, reply) => {{
    try {{
      const rows = await db.execute(`SELECT * FROM {table} ORDER BY id DESC`);
      return reply.send(rows.rows);
    }} catch (err) {{
      fastify.log.error(err);
      return reply.status(500).send({{ error: 'Database error' }});
    }}
  }});

  // POST /{table}
  fastify.post('/{table}', async (req, reply) => {{
    const body = req.body as Record<string, unknown>;
    try {{
      const keys = Object.keys(body).join(', ');
      const vals = Object.values(body);
      const placeholders = vals.map((_, i) => `${{i + 1}}`).join(', ');
      const result = await db.execute(
        `INSERT INTO {table} (${{keys}}) VALUES (${{placeholders}}) RETURNING *`,
        vals,
      );
      return reply.status(201).send(result.rows[0]);
    }} catch (err) {{
      fastify.log.error(err);
      return reply.status(500).send({{ error: 'Database error' }});
    }}
  }});

  // GET /{table}/:id
  fastify.get<{{ Params: {{ id: string }} }}>(
    '/{table}/:id',
    async (req, reply) => {{
      const {{ id }} = req.params;
      const result = await db.execute(`SELECT * FROM {table} WHERE id = $1`, [id]);
      if (!result.rows.length) return reply.status(404).send({{ error: '{pascal} not found' }});
      return reply.send(result.rows[0]);
    }},
  );

  // PUT /{table}/:id
  fastify.put<{{ Params: {{ id: string }} }}>(
    '/{table}/:id',
    async (req, reply) => {{
      const {{ id }} = req.params;
      const body = req.body as Record<string, unknown>;
      const sets = Object.keys(body)
        .map((k, i) => `${{k}} = $${{i + 2}}`)
        .join(', ');
      const vals = [id, ...Object.values(body)];
      const result = await db.execute(
        `UPDATE {table} SET ${{sets}}, updated_at = NOW() WHERE id = $1 RETURNING *`,
        vals,
      );
      if (!result.rows.length) return reply.status(404).send({{ error: '{pascal} not found' }});
      return reply.send(result.rows[0]);
    }},
  );

  // DELETE /{table}/:id
  fastify.delete<{{ Params: {{ id: string }} }}>(
    '/{table}/:id',
    async (req, reply) => {{
      await db.execute(`DELETE FROM {table} WHERE id = $1`, [req.params.id]);
      return reply.status(204).send();
    }},
  );
}}
"""


def generate_ts_index(entities: List[Dict[str, Any]], project_name: str) -> str:
    imports = "\n".join(
        f"import {{ {_to_camel(e.get('table', 'item'))}Routes }} from './routes/{_to_pascal(e.get('table', 'item'))}';  // noqa"
        for e in entities
    )
    registers = "\n  ".join(
        f"await fastify.register({_to_camel(e.get('table', 'item'))}Routes, {{ prefix: '/api' }});"
        for e in entities
    )
    return f"""import Fastify from 'fastify';
import cors from '@fastify/cors';
import * as dotenv from 'dotenv';

dotenv.config();

{imports}

const fastify = Fastify({{ logger: true }});

async function main() {{
  await fastify.register(cors, {{ origin: true }});

  fastify.get('/health', async () => ({{ status: 'ok', service: '{project_name}' }}));

  {registers}

  const port = parseInt(process.env.PORT ?? '8000');
  await fastify.listen({{ port, host: '0.0.0.0' }});
  fastify.log.info('{project_name} listening on port ' + port);
}}

main().catch((err) => {{
  console.error(err);
  process.exit(1);
}});
"""


def generate_node_dockerfile() -> str:
    return """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY package.json .
EXPOSE 8000
CMD ["node", "dist/index.js"]
"""


def generate_env_example() -> str:
    return """PORT=8000
DATABASE_URL=postgres://user:password@localhost:5432/appdb?sslmode=disable
JWT_SECRET=change-me-in-production
"""


async def generate_node_project(
    entities: List[Dict[str, Any]],
    project_name: str,
    output_dir: Path,
) -> Path:
    """
    Generate a complete TypeScript/Fastify project under output_dir/backend/.
    Returns the path to the backend directory.
    """
    backend_dir = output_dir / "backend"
    (backend_dir / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (backend_dir / "src" / "models").mkdir(parents=True, exist_ok=True)

    (backend_dir / "package.json").write_text(generate_package_json(project_name))
    (backend_dir / "tsconfig.json").write_text(generate_tsconfig())
    (backend_dir / "src" / "db.ts").write_text(generate_ts_db())
    (backend_dir / ".env.example").write_text(generate_env_example())
    (backend_dir / "Dockerfile").write_text(generate_node_dockerfile())
    (backend_dir / "src" / "index.ts").write_text(generate_ts_index(entities, project_name))

    for entity in entities:
        table = entity.get("table", "item")
        pascal = _to_pascal(table)
        (backend_dir / "src" / "models" / f"{pascal}.ts").write_text(generate_ts_model(entity))
        (backend_dir / "src" / "routes" / f"{pascal}.ts").write_text(generate_ts_route(entity))

    logger.info(
        "node_generator: wrote %d entities to %s",
        len(entities), backend_dir,
    )
    return backend_dir
