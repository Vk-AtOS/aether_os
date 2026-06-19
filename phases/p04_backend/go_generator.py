"""
Go/Gin REST API generator for AetherOS P04 backend phase.

Called when build_profile.backend_lang == "go". Generates a complete,
runnable Go + Gin project from the domain IR entities.

Output layout (under output_dir/):
  main.go
  handlers/<Entity>Handler.go
  models/<Entity>.go
  db/database.go
  go.mod
  Dockerfile
  .env.example
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Module name used in go.mod — derived from project slug at generation time
_DEFAULT_MODULE = "github.com/aetheros/generated-app"


def _to_pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.replace("-", "_").split("_"))


def _to_camel(name: str) -> str:
    parts = name.replace("-", "_").split("_")
    return parts[0].lower() + "".join(w.capitalize() for w in parts[1:])


def generate_go_mod(module_name: str) -> str:
    return f"""module {module_name}

go 1.21

require (
\tgithub.com/gin-gonic/gin v1.9.1
\tgorm.io/gorm v1.25.5
\tgorm.io/driver/postgres v1.5.4
\tgorm.io/driver/sqlite v1.5.4
\tgithub.com/golang-jwt/jwt/v5 v5.2.0
\tgithub.com/joho/godotenv v1.5.1
\tgolang.org/x/crypto v0.17.0
)
"""


def generate_go_model(entity: Dict[str, Any]) -> str:
    table = entity.get("table", "item")
    pascal = _to_pascal(table)
    fields = entity.get("fields", [])

    go_fields = [
        "\tID        uint           `gorm:\"primarykey\" json:\"id\"`",
        "\tCreatedAt time.Time      `json:\"created_at\"`",
        "\tUpdatedAt time.Time      `json:\"updated_at\"`",
    ]
    for f in fields:
        fname = f.get("name", "field")
        ftype = f.get("type", "string").lower()
        go_type = {
            "string": "string", "text": "string", "int": "int",
            "integer": "int", "float": "float64", "bool": "bool",
            "boolean": "bool", "datetime": "time.Time", "date": "time.Time",
            "fk": "uint",
        }.get(ftype, "string")
        go_tag = f"`gorm:\"column:{fname}\" json:\"{fname}\"`"
        go_fields.append(f"\t{_to_pascal(fname):<20} {go_type:<10} {go_tag}")

    fields_str = "\n".join(go_fields)
    return f"""package models

import "time"

// {pascal} maps to the {table} database table.
type {pascal} struct {{
{fields_str}
}}

func ({pascal}) TableName() string {{ return "{table}" }}
"""


def generate_go_handler(entity: Dict[str, Any], module_name: str) -> str:
    table = entity.get("table", "item")
    pascal = _to_pascal(table)
    camel = _to_camel(table)

    return f"""package handlers

import (
\t"net/http"
\t"strconv"

\t"github.com/gin-gonic/gin"
\t"{module_name}/db"
\t"{module_name}/models"
)

// List{pascal} GET /{table}
func List{pascal}(c *gin.Context) {{
\tvar items []models.{pascal}
\tif err := db.DB.Find(&items).Error; err != nil {{
\t\tc.JSON(http.StatusInternalServerError, gin.H{{"error": err.Error()}})
\t\treturn
\t}}
\tc.JSON(http.StatusOK, items)
}}

// Create{pascal} POST /{table}
func Create{pascal}(c *gin.Context) {{
\tvar item models.{pascal}
\tif err := c.ShouldBindJSON(&item); err != nil {{
\t\tc.JSON(http.StatusBadRequest, gin.H{{"error": err.Error()}})
\t\treturn
\t}}
\tif err := db.DB.Create(&item).Error; err != nil {{
\t\tc.JSON(http.StatusInternalServerError, gin.H{{"error": err.Error()}})
\t\treturn
\t}}
\tc.JSON(http.StatusCreated, item)
}}

// Get{pascal} GET /{table}/:id
func Get{pascal}(c *gin.Context) {{
\tid, _ := strconv.Atoi(c.Param("id"))
\tvar item models.{pascal}
\tif err := db.DB.First(&item, id).Error; err != nil {{
\t\tc.JSON(http.StatusNotFound, gin.H{{"error": "{pascal} not found"}})
\t\treturn
\t}}
\tc.JSON(http.StatusOK, item)
}}

// Update{pascal} PUT /{table}/:id
func Update{pascal}(c *gin.Context) {{
\tid, _ := strconv.Atoi(c.Param("id"))
\tvar item models.{pascal}
\tif err := db.DB.First(&item, id).Error; err != nil {{
\t\tc.JSON(http.StatusNotFound, gin.H{{"error": "{pascal} not found"}})
\t\treturn
\t}}
\tif err := c.ShouldBindJSON(&item); err != nil {{
\t\tc.JSON(http.StatusBadRequest, gin.H{{"error": err.Error()}})
\t\treturn
\t}}
\tdb.DB.Save(&item)
\tc.JSON(http.StatusOK, item)
}}

// Delete{pascal} DELETE /{table}/:id
func Delete{pascal}(c *gin.Context) {{
\tid, _ := strconv.Atoi(c.Param("id"))
\tif err := db.DB.Delete(&models.{pascal}{{}}, id).Error; err != nil {{
\t\tc.JSON(http.StatusInternalServerError, gin.H{{"error": err.Error()}})
\t\treturn
\t}}
\tc.JSON(http.StatusNoContent, nil)
}}

// Register{pascal}Routes wires all {camel} routes onto the given router group.
func Register{pascal}Routes(rg *gin.RouterGroup) {{
\trg.GET("/{table}", List{pascal})
\trg.POST("/{table}", Create{pascal})
\trg.GET("/{table}/:id", Get{pascal})
\trg.PUT("/{table}/:id", Update{pascal})
\trg.DELETE("/{table}/:id", Delete{pascal})
}}
"""


def generate_go_db(db_driver: str = "postgres") -> str:
    if db_driver == "sqlite":
        driver_import = 'gorm.io/driver/sqlite'
        open_expr = 'sqlite.Open(os.Getenv("DATABASE_PATH"))'
    else:
        driver_import = 'gorm.io/driver/postgres'
        open_expr = 'postgres.Open(os.Getenv("DATABASE_URL"))'

    return f"""package db

import (
\t"log"
\t"os"

\t"{driver_import}"
\t"gorm.io/gorm"
)

var DB *gorm.DB

func Init(models ...interface{{}}) {{
\tvar err error
\tDB, err = gorm.Open({open_expr}, &gorm.Config{{}})
\tif err != nil {{
\t\tlog.Fatalf("Failed to connect to database: %v", err)
\t}}
\tif err := DB.AutoMigrate(models...); err != nil {{
\t\tlog.Fatalf("AutoMigrate failed: %v", err)
\t}}
}}
"""


def generate_go_main(
    entities: List[Dict[str, Any]],
    project_name: str,
    module_name: str,
    db_driver: str = "postgres",
) -> str:
    handler_imports = "\n".join(
        f'\t"{module_name}/handlers"' for _ in [entities[0]] if entities
    )
    route_regs = "\n\t".join(
        f"handlers.Register{_to_pascal(e.get('table', 'item'))}Routes(api)"
        for e in entities
    )
    model_refs = ", ".join(
        f"&models.{_to_pascal(e.get('table', 'item'))}{{}}" for e in entities
    )
    db_driver_comment = "postgres" if db_driver != "sqlite" else "sqlite"

    return f"""package main

import (
\t"log"
\t"os"

\t"github.com/gin-gonic/gin"
\t"github.com/joho/godotenv"
{handler_imports}
\t"{module_name}/db"
\t"{module_name}/models"
)

func main() {{
\t// Load .env for local development
\tif err := godotenv.Load(); err != nil {{
\t\tlog.Println("No .env file found, using environment variables")
\t}}

\t// Initialise {db_driver_comment} via GORM
\tdb.Init({model_refs})

\tr := gin.Default()

\t// Health check (public)
\tr.GET("/health", func(c *gin.Context) {{
\t\tc.JSON(200, gin.H{{"status": "ok", "service": "{project_name}"}})
\t}})

\tapi := r.Group("/api")
\t{route_regs}

\tport := os.Getenv("PORT")
\tif port == "" {{
\t\tport = "8000"
\t}}
\tlog.Printf("{project_name} listening on :%s", port)
\tif err := r.Run(":" + port); err != nil {{
\t\tlog.Fatalf("Server failed: %v", err)
\t}}
}}
"""


def generate_go_dockerfile(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    return f"""# Multi-stage Go build — final image is ~10MB scratch image
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /app/server .

FROM scratch
COPY --from=builder /app/server /server
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
EXPOSE 8000
ENTRYPOINT ["/server"]
"""


def generate_env_example(db_driver: str = "postgres") -> str:
    if db_driver == "sqlite":
        db_line = 'DATABASE_PATH=./app.db'
    else:
        db_line = 'DATABASE_URL=postgres://user:password@localhost:5432/appdb?sslmode=disable'
    return f"""PORT=8000
{db_line}
JWT_SECRET=change-me-in-production
"""


async def generate_go_project(
    entities: List[Dict[str, Any]],
    project_name: str,
    output_dir: Path,
    db_driver: str = "postgres",
    module_name: str = "",
) -> Path:
    """
    Generate a complete Go/Gin project under output_dir/backend/.
    Returns the path to the backend directory.
    """
    if not module_name:
        slug = project_name.lower().replace(" ", "-").replace("_", "-")
        module_name = f"github.com/aetheros/{slug}"

    backend_dir = output_dir / "backend"
    (backend_dir / "handlers").mkdir(parents=True, exist_ok=True)
    (backend_dir / "models").mkdir(parents=True, exist_ok=True)
    (backend_dir / "db").mkdir(parents=True, exist_ok=True)

    (backend_dir / "go.mod").write_text(generate_go_mod(module_name))
    (backend_dir / "db" / "database.go").write_text(generate_go_db(db_driver))
    (backend_dir / ".env.example").write_text(generate_env_example(db_driver))
    (backend_dir / "Dockerfile").write_text(generate_go_dockerfile(project_name))

    for entity in entities:
        table = entity.get("table", "item")
        pascal = _to_pascal(table)
        (backend_dir / "models" / f"{pascal}.go").write_text(generate_go_model(entity))
        (backend_dir / "handlers" / f"{pascal}Handler.go").write_text(
            generate_go_handler(entity, module_name)
        )

    (backend_dir / "main.go").write_text(
        generate_go_main(entities, project_name, module_name, db_driver)
    )

    logger.info(
        "go_generator: wrote %d entities to %s (module=%s, db=%s)",
        len(entities), backend_dir, module_name, db_driver,
    )
    return backend_dir
