import sys
from pathlib import Path

# Add project root to sys.path to allow imports from src
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

from src.database import Base, engine
from src.models import RepairJob, AuditLog, FailureFingerprint

def migrate():
    print("Dropping all tables...")
    Base.metadata.drop_all(engine)
    print("Creating all tables...")
    Base.metadata.create_all(engine)
    print("Migration complete. Tables recreated.")

    from src.db.tenant_repo import create_tenant, get_tenant_by_slug
    from src.database import SessionLocal
    
    session = SessionLocal()
    try:
        # Create default tenant if not exists
        existing = get_tenant_by_slug(session, "default")
        if not existing:
            t = create_tenant(session, "Default", "enterprise")
            print(f"Created default tenant: {t.id}")
        else:
            print(f"Default tenant exists: {existing.id}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate()
