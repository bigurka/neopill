"""Constants for the NeoPill integration."""

DOMAIN = "neopill"

STORAGE_VERSION = 1
STORAGE_KEY = "neopill.data"

PANEL_URL_PATH = "neopill"
PANEL_TITLE = "NeoPill"
PANEL_ICON = "mdi:pill-multiple"

EVENT_DOSE_DUE = "neopill_dose_due"

SIGNAL_PATIENT_ADDED = f"{DOMAIN}_patient_added"
SIGNAL_PATIENT_REMOVED = f"{DOMAIN}_patient_removed"
SIGNAL_MEDICATION_ADDED = f"{DOMAIN}_medication_added"
SIGNAL_MEDICATION_UPDATED = f"{DOMAIN}_medication_updated"
SIGNAL_MEDICATION_REMOVED = f"{DOMAIN}_medication_removed"
SIGNAL_INTAKE_RECORDED = f"{DOMAIN}_intake_recorded"
SIGNAL_RESTOCK_RECORDED = f"{DOMAIN}_restock_recorded"
SIGNAL_DOSE_DUE_CHANGED = f"{DOMAIN}_dose_due_changed"

DEFAULT_LOW_STOCK_DAYS_THRESHOLD = 7
DEFAULT_SAFETY_SWEEP_INTERVAL_MINUTES = 5

SCHEDULE_TYPE_FIXED_TIMES = "fixed_times"
SCHEDULE_TYPE_INTERVAL = "interval"

INTAKE_STATUS_TAKEN = "taken"
INTAKE_STATUS_MISSED = "missed"

CALENDAR_EVENT_TAKEN = "assunta"
CALENDAR_EVENT_MISSED = "non_assunta"
CALENDAR_EVENT_RESTOCK = "rifornimento"
CALENDAR_EVENT_DEPLETED = "scorta_esaurita"
