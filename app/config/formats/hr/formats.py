DATE_FORMAT = "d.m.Y"
DATETIME_FORMAT = "d.m.Y H:i"
SHORT_DATE_FORMAT = "d.m.Y"
SHORT_DATETIME_FORMAT = "d.m.Y H:i"

# Accept both Croatian styles with and without trailing dot
# because admin flatpickr emits values without trailing dot.
DATE_INPUT_FORMATS = [
    "%d.%m.%Y",
    "%d.%m.%Y.",
    "%d.%m.%y",
    "%d.%m.%y.",
    "%Y-%m-%d",
]

DATETIME_INPUT_FORMATS = [
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y. %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y. %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
]
