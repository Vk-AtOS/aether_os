"""
Seed template for healthcare domain — HIPAA-compliant seed data.

All patient records include full audit trail fields (created_by, updated_by,
accessed_at). PHI fields are marked with HIPAA comments. Diagnosis codes
follow ICD-10 format. Prescriptions use Decimal dosage values.

HIPAA note: this file generates FAKE data only — never use real patient info.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

_PROVIDER_NAMES = [
    ("Dr. Sarah Mitchell", "General Practice"),
    ("Dr. James Okafor", "Pediatrics"),
    ("Dr. Priya Sharma", "Cardiology"),
    ("Dr. Carlos Rivera", "Neurology"),
    ("Dr. Emily Chen", "Dermatology"),
    ("Dr. Robert Walsh", "Orthopedics"),
    ("Dr. Fatima Al-Hassan", "Oncology"),
    ("Dr. Michael Nguyen", "Endocrinology"),
    ("Dr. Laura Bennett", "Psychiatry"),
    ("Dr. David Kim", "Pulmonology"),
]

# ICD-10 diagnosis codes with descriptions
_ICD10_CODES = [
    ("J00", "Common cold"),
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I10", "Essential (primary) hypertension"),
    ("J45.909", "Unspecified asthma, uncomplicated"),
    ("M54.5", "Low back pain"),
    ("F32.9", "Major depressive disorder, single episode, unspecified"),
    ("K21.0", "Gastro-esophageal reflux disease with oesophagitis"),
    ("J06.9", "Acute upper respiratory infection, unspecified"),
    ("N39.0", "Urinary tract infection, site not specified"),
    ("L20.9", "Atopic dermatitis, unspecified"),
    ("G43.909", "Migraine, unspecified, not intractable, without status migrainosus"),
    ("E78.5", "Hyperlipidaemia, unspecified"),
    ("Z00.00", "Encounter for general adult medical examination without abnormal findings"),
    ("M79.3", "Panniculitis, unspecified"),
    ("R51", "Headache"),
    ("J20.9", "Acute bronchitis, unspecified"),
    ("K58.9", "Irritable bowel syndrome without diarrhoea"),
    ("F41.1", "Generalised anxiety disorder"),
    ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    ("Z23", "Encounter for immunization"),
]

# Prescription medications
_MEDICATIONS = [
    ("Metformin", "500.00", "twice_daily"),
    ("Lisinopril", "10.00", "once_daily"),
    ("Atorvastatin", "20.00", "once_daily"),
    ("Albuterol", "2.50", "as_needed"),
    ("Sertraline", "50.00", "once_daily"),
    ("Omeprazole", "20.00", "once_daily"),
    ("Amlodipine", "5.00", "once_daily"),
    ("Levothyroxine", "0.05", "once_daily"),
    ("Ibuprofen", "400.00", "as_needed"),
    ("Amoxicillin", "500.00", "twice_daily"),
    ("Fluoxetine", "20.00", "once_daily"),
    ("Losartan", "50.00", "once_daily"),
    ("Gabapentin", "300.00", "twice_daily"),
    ("Prednisone", "5.00", "as_needed"),
    ("Hydrochlorothiazide", "25.00", "once_daily"),
    ("Citalopram", "20.00", "once_daily"),
    ("Azithromycin", "250.00", "once_daily"),
    ("Cetirizine", "10.00", "once_daily"),
    ("Pantoprazole", "40.00", "once_daily"),
    ("Tramadol", "50.00", "as_needed"),
]

_APPOINTMENT_TYPES = [
    "consultation", "follow_up", "emergency", "surgery", "checkup",
    "consultation", "follow_up", "checkup", "consultation", "follow_up",
    "checkup", "emergency", "consultation", "follow_up", "checkup",
    "consultation", "surgery", "follow_up", "checkup", "consultation",
]

_APPOINTMENT_STATUSES = [
    "completed", "scheduled", "completed", "cancelled", "completed",
    "confirmed", "completed", "no_show", "completed", "scheduled",
    "completed", "completed", "in_progress", "scheduled", "completed",
    "confirmed", "completed", "scheduled", "completed", "no_show",
]


def get_healthcare_seed_data(entities: list[str]) -> dict[str, list[dict]]:
    """Return HIPAA-aware seed data keyed by entity name for the healthcare vertical.

    All patient records include required audit trail fields.
    HIPAA: this data is entirely synthetic — no real PHI.
    """
    result: dict[str, list[dict]] = {}
    now = datetime.utcnow()
    today = date.today()

    # ── 1. Provider ──────────────────────────────────────────────────────────
    if _any_match(entities, ["provider", "providers", "doctor", "doctors"]):
        result["Provider"] = [
            {
                "id": i + 1,
                "full_name": name,
                "specialty": specialty,
                "license_number": f"LIC-{(i+1):06d}",
                "email": f"provider{i+1:03d}@clinic-example.com",  # unique
                "phone": f"+1-800-{(2000 + i):04d}",
                "is_active": True,
                # Audit trail — required on all healthcare models
                "created_by": "system",
                "updated_by": "system",
                "accessed_at": None,
                "created_at": (now - timedelta(days=500 - i * 20)).isoformat(),
                "updated_at": (now - timedelta(days=30)).isoformat(),
            }
            for i, (name, specialty) in enumerate(_PROVIDER_NAMES)
        ]

    # ── 2. Patient ───────────────────────────────────────────────────────────
    # HIPAA: PHI fields below — never log any of these values
    if _any_match(entities, ["patient", "patients"]):
        result["Patient"] = [
            {
                "id": i + 1,
                "medical_record_number": f"MRN-{(i+1):06d}",  # unique, indexed
                # HIPAA: never log this field
                "full_name": f"Patient {_FIRST_NAMES[i]} {_LAST_NAMES[i]}",
                # HIPAA: never log this field
                "email": f"patient{i+1:03d}@example-health.com",  # unique
                # HIPAA: never log this field
                "date_of_birth": str(date(1970 + i, (i % 12) + 1, (i % 28) + 1)),
                # HIPAA: never log this field
                "phone": f"+1-555-{(3000 + i):04d}",
                "gender": ["M", "F", "M", "F", "M", "F", "M", "F", "M", "F",
                           "M", "F", "M", "F", "M", "F", "M", "F", "M", "F"][i],
                "blood_type": ["A+", "B+", "O+", "AB+", "A-", "B-", "O-", "AB+",
                               "A+", "O+", "B+", "A+", "O-", "AB-", "A+", "B+",
                               "O+", "A-", "B+", "O+"][i],
                "insurance_id": f"INS-{(i+1):08d}",
                "is_active": True,
                # Full audit trail — required for all patient records (HIPAA §164.312)
                "created_by": "system",
                "updated_by": "system",
                "accessed_at": now.isoformat(),  # record last access time
                "created_at": (now - timedelta(days=400 - i * 15)).isoformat(),
                "updated_at": (now - timedelta(days=20 - i % 20)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 3. Appointment ───────────────────────────────────────────────────────
    if _any_match(entities, ["appointment", "appointments"]):
        result["Appointment"] = [
            {
                "id": i + 1,
                "patient_id": (i % 20) + 1,   # references Patient that exists
                "provider_id": (i % 10) + 1,  # references Provider that exists
                "appointment_type": _APPOINTMENT_TYPES[i],
                "status": _APPOINTMENT_STATUSES[i],
                "appointment_date": str(today + timedelta(days=(i - 10))),
                "appointment_time": f"{(8 + i % 10):02d}:00:00",
                "duration_minutes": [30, 45, 60, 90, 30][i % 5],
                "notes": f"Routine {_APPOINTMENT_TYPES[i]} — patient reports improvement.",
                "room_number": f"R{(101 + i % 20):03d}",
                # Audit trail — required
                "created_by": "system",
                "updated_by": "system",
                "accessed_at": None,
                "created_at": (now - timedelta(days=30 - i)).isoformat(),
                "updated_at": (now - timedelta(days=5)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 4. MedicalRecord ─────────────────────────────────────────────────────
    if _any_match(entities, ["medicalrecord", "medical_record", "medicalrecords"]):
        result["MedicalRecord"] = [
            {
                "id": i + 1,
                "patient_id": (i % 20) + 1,       # references Patient
                "provider_id": (i % 10) + 1,      # references Provider
                "appointment_id": (i % 20) + 1,   # references Appointment
                "icd10_code": _ICD10_CODES[i][0],
                "diagnosis": _ICD10_CODES[i][1],
                "clinical_notes": (
                    f"Patient presented with {_ICD10_CODES[i][1].lower()}. "
                    "Vitals stable. Treatment plan initiated."
                ),
                # HIPAA: file attachments store path only — no binary BLOB in DB
                "attachment_path": f"/secure/records/patient-{(i%20)+1}/record-{i+1:04d}.pdf",
                # Audit trail — required (HIPAA §164.312)
                "created_by": f"provider_{(i % 10) + 1}",
                "updated_by": f"provider_{(i % 10) + 1}",
                "accessed_at": (now - timedelta(hours=i * 2)).isoformat(),
                "created_at": (now - timedelta(days=60 - i * 3)).isoformat(),
                "updated_at": (now - timedelta(days=30 - i % 30)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 5. Prescription ──────────────────────────────────────────────────────
    if _any_match(entities, ["prescription", "prescriptions"]):
        result["Prescription"] = [
            {
                "id": i + 1,
                "patient_id": (i % 20) + 1,   # references Patient
                "provider_id": (i % 10) + 1,  # references Provider
                "medication_name": _MEDICATIONS[i][0],
                "dosage_mg": _MEDICATIONS[i][1],   # Decimal string → Numeric(8,2)
                "frequency": _MEDICATIONS[i][2],   # Enum: once_daily/twice_daily/as_needed
                "refills_remaining": (i % 6),
                "start_date": str(today - timedelta(days=30 - i)),
                "end_date": str(today + timedelta(days=60)),
                "is_active": (i % 7 != 6),
                "pharmacy_notes": f"Dispense {30 + (i % 30)} units. No substitutions.",
                # Audit trail
                "created_by": f"provider_{(i % 10) + 1}",
                "updated_by": f"provider_{(i % 10) + 1}",
                "accessed_at": None,
                "created_at": (now - timedelta(days=30 - i)).isoformat(),
                "updated_at": (now - timedelta(days=10)).isoformat(),
            }
            for i in range(20)
        ]

    # ── 6. LabResult ─────────────────────────────────────────────────────────
    if _any_match(entities, ["labresult", "lab_result", "labresults"]):
        _lab_tests = [
            "Complete Blood Count", "Basic Metabolic Panel", "Lipid Panel",
            "HbA1c", "Thyroid Panel", "Urinalysis", "Comprehensive Metabolic Panel",
            "Vitamin D", "Iron Panel", "COVID-19 PCR",
        ]
        result["LabResult"] = [
            {
                "id": i + 1,
                "patient_id": (i % 20) + 1,
                "provider_id": (i % 10) + 1,
                "test_name": _lab_tests[i % 10],
                "result_value": f"{(95 + i * 3) % 200}",
                "unit": ["mg/dL", "mmol/L", "%", "U/L", "mIU/L"][i % 5],
                "reference_range": "70–100",
                "is_abnormal": (i % 5 == 4),
                "collected_at": (now - timedelta(days=15 - i % 15)).isoformat(),
                "reported_at": (now - timedelta(days=14 - i % 14)).isoformat(),
                # HIPAA: file path only — no binary data in DB
                "report_path": f"/secure/labs/patient-{(i%20)+1}/lab-{i+1:04d}.pdf",
                # Audit trail
                "created_by": "lab_system",
                "updated_by": "lab_system",
                "accessed_at": None,
                "created_at": (now - timedelta(days=15 - i % 15)).isoformat(),
                "updated_at": (now - timedelta(days=14 - i % 14)).isoformat(),
            }
            for i in range(20)
        ]

    return result


def _any_match(entities: list[str], candidates: list[str]) -> bool:
    """Return True if any entity name (case-insensitive) matches a candidate."""
    lower_entities = [e.lower() for e in entities]
    return any(c in lower_entities for c in candidates)


_FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John",
    "Jennifer", "Michael", "Linda", "William", "Barbara",
    "David", "Susan", "Richard", "Jessica", "Joseph",
    "Sarah", "Thomas", "Karen", "Charles", "Nancy",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Garcia", "Miller", "Davis", "Wilson", "Martinez",
    "Anderson", "Taylor", "Thomas", "Jackson", "White",
    "Harris", "Martin", "Thompson", "Young", "Robinson",
]
