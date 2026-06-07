"""
Seed template for healthcare domain.
"""
from sqlalchemy import select, func
from datetime import date, timedelta
from models import User, Patient, Provider, Appointment, MedicalRecord

async def seed_healthcare(db_session):
    # 1. Providers
    providers = [
        Provider(name="Dr. Smith", specialty="General Practice", bio="Experienced GP"),
        Provider(name="Dr. Jones", specialty="Pediatrics", bio="Pediatric specialist"),
        Provider(name="Dr. Taylor", specialty="Cardiology", bio="Heart health expert"),
        Provider(name="Dr. Brown", specialty="Neurology", bio="Brain specialist"),
        Provider(name="Dr. White", specialty="Dermatology", bio="Skin expert"),
    ]
    db_session.add_all(providers)
    await db_session.flush()

    # 2. Patients
    patients = []
    names = ["John Doe", "Jane Roe", "Sam Smith", "Lisa Ray", "Mike Ross", 
             "Rachel Zane", "Harvey Specter", "Donna Paulsen", "Louis Litt", "Jessica Pearson",
             "Tom Hardy", "Emily Blunt", "Chris Pratt", "Zoe Saldana", "Robert Downey",
             "Scarlett Johansson", "Chris Evans", "Mark Ruffalo", "Jeremy Renner", "Paul Rudd"]
    for i, name in enumerate(names):
        p = Patient(
            full_name=name,
            email=f"{name.lower().replace(' ', '.')}@example.com",
            date_of_birth=str(date(1980, 1, 1) + timedelta(days=i*365)),
            phone=f"555-01{i:02d}"
        )
        patients.append(p)
    db_session.add_all(patients)
    await db_session.flush()

    # 3. Appointments (FK to Patient and Provider)
    today = date.today()
    appointments = []
    for i in range(30):
        # Spread appointments around today
        app_date = today + timedelta(days=(i - 15))
        app = Appointment(
            patient_id=patients[i % len(patients)].id,
            provider_id=providers[i % len(providers)].id,
            appointment_date=str(app_date),
            status="scheduled" if app_date >= today else "completed",
            notes=f"Routine checkup {i+1}"
        )
        appointments.append(app)
    db_session.add_all(appointments)
    
    await db_session.commit()
