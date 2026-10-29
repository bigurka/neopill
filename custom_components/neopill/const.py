"""Constants for the NeoPill integration."""

DOMAIN = "neopill"

STORAGE_VERSION = 1
STORAGE_KEY = "neopill.data"

PANEL_URL_PATH = "neopill"
PANEL_TITLE = "NeoPill"
PANEL_ICON = "mdi:pill-multiple"

EVENT_DOSE_DUE = "neopill_dose_due"
# Fired whenever a "taken" intake brings a medication's stock to zero - lets an
# automation (see the neopill_stock_depleted_notice blueprint) offer a quick
# "actually, undo that" button, especially useful after a bulk "take all" action
# where an individual medication can't be deselected beforehand.
EVENT_STOCK_DEPLETED = "neopill_stock_depleted"

SIGNAL_PATIENT_ADDED = f"{DOMAIN}_patient_added"
SIGNAL_PATIENT_UPDATED = f"{DOMAIN}_patient_updated"
SIGNAL_PATIENT_REMOVED = f"{DOMAIN}_patient_removed"
SIGNAL_MEDICATION_ADDED = f"{DOMAIN}_medication_added"
SIGNAL_MEDICATION_UPDATED = f"{DOMAIN}_medication_updated"
SIGNAL_MEDICATION_REMOVED = f"{DOMAIN}_medication_removed"
SIGNAL_INTAKE_RECORDED = f"{DOMAIN}_intake_recorded"
SIGNAL_RESTOCK_RECORDED = f"{DOMAIN}_restock_recorded"
SIGNAL_DOSE_DUE_CHANGED = f"{DOMAIN}_dose_due_changed"
SIGNAL_RESTOCK_NOTIFY_CHANGED = f"{DOMAIN}_restock_notify_changed"

DEFAULT_LOW_STOCK_DAYS_THRESHOLD = 7
DEFAULT_SAFETY_SWEEP_INTERVAL_MINUTES = 5

# Default "ideal reorder window" (in days-of-stock-remaining) for a new patient -
# a medication surfaces in the "farmaci da rifornire" sensor once its estimated
# days remaining falls at or below the max and at or above the min. Editable per
# patient afterwards (not a global constant once a patient exists).
DEFAULT_RESTOCK_WINDOW_MIN_DAYS = 7
DEFAULT_RESTOCK_WINDOW_MAX_DAYS = 14

SCHEDULE_TYPE_FIXED_TIMES = "fixed_times"
SCHEDULE_TYPE_INTERVAL = "interval"
SCHEDULE_TYPE_WEEKLY = "weekly"

# Monday-first, matching Python's date.weekday() (Monday == 0)
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

INTAKE_STATUS_TAKEN = "taken"
INTAKE_STATUS_MISSED = "missed"
# Auto-recorded by DoseScheduler at midnight (or on restart, for a day already crossed)
# for a dose that was never answered (neither taken nor explicitly marked missed) -
# distinct from INTAKE_STATUS_MISSED, which is always a deliberate user action.
INTAKE_STATUS_UNANSWERED = "unanswered"

CALENDAR_EVENT_TAKEN = "assunta"
CALENDAR_EVENT_MISSED = "non_assunta"
CALENDAR_EVENT_UNANSWERED = "nessuna_risposta"
CALENDAR_EVENT_RESTOCK = "rifornimento"
CALENDAR_EVENT_DEPLETED = "scorta_esaurita"
