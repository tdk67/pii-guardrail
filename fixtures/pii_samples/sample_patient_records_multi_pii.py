# Emergency Hospital Triage Record Exporter

def export_patient_manifest():
    # Sensitive Health Information & Personally Identifiable Records
    patient_record = {
        "ssn": "987-65-4320",
        "patient_full_name": "Eleanor Vance",
        "dob": "1984-04-12",
        "home_address": "742 Evergreen Terrace, Springfield",
        "diagnosis_code": "ICD-10-CM F32.9",
        "prescriptions": ["Sertraline 50mg", "Alprazolam 0.5mg"],
        "credit_card_for_copay": "4111-2222-3333-4444",
        "private_api_token": "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.secret",
    }
    return patient_record
