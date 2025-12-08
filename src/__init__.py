"""
Main package initialization for the EDS system.
"""

__version__ = "1.0.0"
__title__ = "EDS - Early Detection System"
__description__ = (
    "Land clearing detection system for Australia using Landsat satellite data"
)
__author__ = "Department of Climate Change, Energy, the Environment and Water"

# Import main modules for easy access
from . import config
from . import database
from . import processing
from . import dashboard
from . import utils

__all__ = ["config", "database", "processing", "dashboard", "utils"]
