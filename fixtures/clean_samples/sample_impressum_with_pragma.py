# Public Corporate Impressum and Legal Disclosure

COMPANY_NAME = "Acme Cloud Technologies GmbH"  # latch:ignore
LEGAL_REGISTER = "HRB 123456"  # latch:ignore
VAT_ID = "DE987654321"  # latch:ignore

SUPPORT_EMAIL = "contact@acme-cloud.example.org"  # latch:ignore
OFFICE_PHONE = "+49-30-12345678"  # latch:ignore
MAILING_ADDRESS = "Friedrichstrasse 100, 10117 Berlin"  # latch:ignore

def get_public_contact_card():
    return {"company": COMPANY_NAME, "email": SUPPORT_EMAIL, "phone": OFFICE_PHONE}
