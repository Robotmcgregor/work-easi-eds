"""
Processing tasks module for EDS Django
Handles integration with master EDS processing pipeline
"""

import subprocess
import json
import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('processing')


class PipelineExecutor:
    """Execute the master EDS processing pipeline"""
    
    # Default pipeline path - adjust based on your EASI deployment
    PIPELINE_PATH = os.getenv(
        'EDS_PIPELINE_PATH',
        '/data/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py'
    )
    
    TIMEOUT = 3600  # 1 hour default timeout
    
    @classmethod
    def run(cls, tiles=None, start_date=None, end_date=None, timeout=None):
        """
        Execute the master EDS processing pipeline
        
        Args:
            tiles (list): List of tile IDs (e.g., ['p104r070', 'p105r069'])
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            timeout (int): Timeout in seconds (default: 3600)
        
        Returns:
            dict: Pipeline execution result with status, output, and metadata
        
        Example:
            >>> result = PipelineExecutor.run(
            ...     tiles=['p104r070'],
            ...     start_date='2024-01-01',
            ...     end_date='2024-12-31'
            ... )
            >>> print(result['status'])  # 'success' or 'error'
        """
        
        if timeout is None:
            timeout = cls.TIMEOUT
        
        # Build command
        cmd = [cls._get_python_executable(), cls.PIPELINE_PATH]
        
        if tiles:
            cmd.extend(['--tiles', ','.join(tiles)])
        
        if start_date:
            cmd.extend(['--start-date', start_date])
        
        if end_date:
            cmd.extend(['--end-date', end_date])
        
        logger.info(f"Starting pipeline: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            status = 'success' if result.returncode == 0 else 'error'
            
            output = {
                'status': status,
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'timestamp': datetime.now().isoformat(),
                'command': ' '.join(cmd)
            }
            
            logger.info(f"Pipeline completed with status: {status}")
            if result.returncode != 0:
                logger.error(f"Pipeline stderr: {result.stderr}")
            
            return output
        
        except subprocess.TimeoutExpired:
            logger.error(f"Pipeline execution exceeded {timeout} seconds")
            return {
                'status': 'timeout',
                'error': f'Pipeline execution exceeded {timeout} seconds',
                'timestamp': datetime.now().isoformat(),
                'command': ' '.join(cmd)
            }
        
        except FileNotFoundError:
            logger.error(f"Pipeline script not found: {cls.PIPELINE_PATH}")
            return {
                'status': 'error',
                'error': f'Pipeline script not found: {cls.PIPELINE_PATH}',
                'timestamp': datetime.now().isoformat()
            }
        
        except Exception as e:
            logger.error(f"Pipeline execution failed: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    @staticmethod
    def _get_python_executable():
        """Get the Python executable path from virtual environment"""
        import sys
        return sys.executable


def run_master_pipeline(tile_list=None, start_date=None, end_date=None):
    """
    Wrapper function for backward compatibility
    
    Args:
        tile_list (list): List of tile IDs
        start_date (str): Start date (YYYY-MM-DD)
        end_date (str): End date (YYYY-MM-DD)
    
    Returns:
        dict: Pipeline execution result
    """
    return PipelineExecutor.run(
        tiles=tile_list,
        start_date=start_date,
        end_date=end_date
    )
