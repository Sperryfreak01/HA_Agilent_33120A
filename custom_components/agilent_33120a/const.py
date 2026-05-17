DOMAIN = "agilent_33120a"

DEFAULT_PORT = 6638
DEFAULT_POLL_INTERVAL = 2  # seconds
DEFAULT_TERMINATION = "50"

SHAPES = ("SIN", "SQU", "TRI")
SHAPE_LABELS = {"SIN": "sine", "SQU": "square", "TRI": "triangle"}

FREQ_LIMITS = {
    "SIN": (1e-4, 1.5e7),
    "SQU": (1e-4, 1.5e7),
    "TRI": (1e-4, 1.0e5),
}

AMP_LIMITS = {
    "50":  (0.05, 10.0),   # Vpp into 50 Ω
    "INF": (0.10, 20.0),   # Vpp into high-Z
}

VMAX = {"50": 5.0, "INF": 10.0}

CONF_HOST = "host"
CONF_PORT = "port"
CONF_TERMINATION = "termination"
CONF_POLL_INTERVAL = "poll_interval"
