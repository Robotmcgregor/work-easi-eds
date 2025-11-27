"""
Processing package initialization.
"""

from .pipeline import EDSProcessor, EDSPipelineManager, ProcessingConfig, ProcessingResult
from .scheduler import EDSScheduler, eds_scheduler, start_scheduler, stop_scheduler, get_scheduler_status

__all__ = [
    'EDSProcessor',
    'EDSPipelineManager', 
    'ProcessingConfig',
    'ProcessingResult',
    'EDSScheduler',
    'eds_scheduler',
    'start_scheduler',
    'stop_scheduler',
    'get_scheduler_status'
]