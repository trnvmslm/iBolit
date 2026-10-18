"""User roles."""


class Role:
    PATIENT = "patient"
    DOCTOR = "doctor"
    LAB_SPECIALIST = "lab_specialist"
    PHARMACIST = "pharmacist"
    INTERN = "intern"
    SUPPORT = "support"
    ADMIN = "admin"

    CLINICIANS = frozenset({DOCTOR, LAB_SPECIALIST})
    STAFF = frozenset({SUPPORT, ADMIN})
    ALL = frozenset({PATIENT, DOCTOR, LAB_SPECIALIST, PHARMACIST, INTERN, SUPPORT, ADMIN})
