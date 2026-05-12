"""
Scheduler for automated EDS processing tasks.
"""

import schedule
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
import threading

from .pipeline import EDSPipelineManager, ProcessingConfig
from ..database import SystemStatusManager

logger = logging.getLogger(__name__)


class EDSScheduler:
    """
    Scheduler for automated EDS processing tasks.

    Handles regular processing of tiles, system health checks,
    and maintenance tasks.
    """

    def __init__(self):
        """Initialize the EDS scheduler."""
        self.is_running = False
        self.scheduler_thread = None

        # Setup default schedule
        self._setup_default_schedule()

    def _setup_default_schedule(self):
        """Set up the default processing schedule."""

        # Daily automatic processing at 2 AM
        schedule.every().day.at("02:00").do(self._run_daily_processing)

        # Hourly quick check for urgent tiles (last processed > 48h ago)
        schedule.every().hour.do(self._run_urgent_processing)

        # System health check every 15 minutes
        schedule.every(15).minutes.do(self._run_health_check)

        # Weekly full processing run on Sundays at 1 AM
        schedule.every().sunday.at("01:00").do(self._run_weekly_full_processing)

        logger.info("Default EDS processing schedule configured")

    def _run_daily_processing(self):
        """Run daily automatic processing."""
        try:
            logger.info("Starting scheduled daily processing")

            # Process tiles that haven't been processed in the last 24 hours
            config = EDSPipelineManager.create_processing_config(days_back=1)
            results = EDSPipelineManager.run_automatic_processing(
                hours_since_last=24, config=config
            )

            successful = sum(1 for r in results if r.success)
            total_alerts = sum(r.alerts_detected for r in results)

            logger.info(
                f"Daily processing complete: {successful}/{len(results)} tiles successful, "
                f"{total_alerts} alerts detected"
            )

            # Update system status
            SystemStatusManager.update_system_status("healthy")

        except Exception as e:
            logger.error(f"Daily processing failed: {e}")
            SystemStatusManager.update_system_status("error")

    def _run_urgent_processing(self):
        """Run processing for urgent tiles (not processed in > 48h)."""
        try:
            # Only process tiles that are really overdue
            config = EDSPipelineManager.create_processing_config(days_back=2)
            results = EDSPipelineManager.run_automatic_processing(
                hours_since_last=48, config=config
            )

            if results:
                successful = sum(1 for r in results if r.success)
                logger.info(
                    f"Urgent processing complete: {successful}/{len(results)} tiles processed"
                )

        except Exception as e:
            logger.error(f"Urgent processing failed: {e}")

    def _run_weekly_full_processing(self):
        """Run weekly full processing of all tiles."""
        try:
            logger.info("Starting scheduled weekly full processing")

            # Process all tiles with a 7-day lookback
            config = EDSPipelineManager.create_processing_config(
                days_back=7, max_concurrent_jobs=6  # Use more resources for weekly run
            )
            results = EDSPipelineManager.run_automatic_processing(
                hours_since_last=168, config=config  # 7 days
            )

            successful = sum(1 for r in results if r.success)
            total_alerts = sum(r.alerts_detected for r in results)

            logger.info(
                f"Weekly processing complete: {successful}/{len(results)} tiles successful, "
                f"{total_alerts} alerts detected"
            )

        except Exception as e:
            logger.error(f"Weekly processing failed: {e}")
            SystemStatusManager.update_system_status("error")

    def _run_health_check(self):
        """Run system health check."""
        try:
            # Basic health check
            from ..database import db_manager

            if db_manager.health_check():
                SystemStatusManager.update_system_status("healthy")
            else:
                logger.warning("Database health check failed")
                SystemStatusManager.update_system_status("warning")

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            SystemStatusManager.update_system_status("error")

    def start(self):
        """Start the scheduler in a background thread."""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return

        self.is_running = True
        self.scheduler_thread = threading.Thread(
            target=self._run_scheduler, daemon=True
        )
        self.scheduler_thread.start()

        logger.info("EDS Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)

        logger.info("EDS Scheduler stopped")

    def _run_scheduler(self):
        """Run the scheduler loop."""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(60)

    def add_custom_job(self, job_func, schedule_spec: str):
        """
        Add a custom scheduled job.

        Args:
            job_func: Function to execute
            schedule_spec: Schedule specification (e.g., "daily", "hourly", "every().day.at('10:00')")
        """
        # This would need more sophisticated parsing for complex schedules
        if schedule_spec == "daily":
            schedule.every().day.do(job_func)
        elif schedule_spec == "hourly":
            schedule.every().hour.do(job_func)
        else:
            logger.warning(f"Unsupported schedule specification: {schedule_spec}")

    def get_next_jobs(self, count: int = 5) -> list:
        """Get information about the next scheduled jobs."""
        jobs = schedule.jobs[:count]
        return [
            {
                "job": str(job.job_func),
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "interval": str(job.interval),
                "unit": job.start_day,
            }
            for job in jobs
        ]


# Global scheduler instance
eds_scheduler = EDSScheduler()


def start_scheduler():
    """Start the global EDS scheduler."""
    eds_scheduler.start()


def stop_scheduler():
    """Stop the global EDS scheduler."""
    eds_scheduler.stop()


def get_scheduler_status():
    """Get the current scheduler status."""
    return {
        "running": eds_scheduler.is_running,
        "next_jobs": eds_scheduler.get_next_jobs(),
    }
