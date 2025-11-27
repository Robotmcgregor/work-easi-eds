"""
Configuration management for the EDS application.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict, field
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    host: str = "localhost"
    port: int = 5432
    username: str = "eds_user"
    password: str = "eds_password"
    database: str = "eds_database"
    
    @property
    def connection_url(self) -> str:
        """Get the PostgreSQL connection URL."""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class ProcessingConfig:
    """EDS processing configuration."""
    # Default processing parameters
    confidence_threshold: float = 0.7
    min_clearing_area_ha: float = 1.0
    max_cloud_coverage: float = 20.0
    
    # Resource limits
    max_concurrent_jobs: int = 4
    timeout_minutes: int = 60
    
    # Output settings
    output_directory: str = "data/processing_results"
    save_intermediate_files: bool = False
    
    # Scheduling settings
    enable_scheduler: bool = True
    daily_processing_time: str = "02:00"  # 24h format
    urgent_processing_hours: int = 48
    
    # Data source settings
    landsat_data_source: str = "aws"  # aws, gcs, local
    data_cache_directory: str = "data/cache"


@dataclass
class S3Config:
    """S3/AWS configuration for data access and storage."""
    bucket: str = ""  # e.g., my-eds-bucket
    region: str = os.environ.get("AWS_REGION", "")
    profile: str = os.environ.get("AWS_PROFILE", "")
    endpoint_url: str = os.environ.get("S3_ENDPOINT_URL", "")  # for S3-compatible stores
    role_arn: str = os.environ.get("S3_ROLE_ARN", "")  # optional: assume role
    base_prefix: str = ""  # e.g., "landsat"


@dataclass
class USGSConfig:
    """USGS M2M configuration for searching and downloading scenes."""
    username: str = os.environ.get("USGS_USERNAME", "")
    password: str = os.environ.get("USGS_PASSWORD", "")
    token: str = os.environ.get("USGS_TOKEN", "")
    endpoint: str = os.environ.get("USGS_M2M_ENDPOINT", "https://m2m.cr.usgs.gov/api/api/json/stable/")
    dataset: str = os.environ.get("USGS_DATASET", "LANDSAT_8_C2_L1")  # Example; adjust per collection
    node: str = os.environ.get("USGS_NODE", "EE")  # 'EE' EarthExplorer node


@dataclass 
class DashboardConfig:
    """Dashboard application configuration."""
    host: str = "0.0.0.0"
    port: int = 8050
    debug: bool = False
    
    # Update intervals (seconds)
    data_refresh_interval: int = 30
    chart_refresh_interval: int = 60
    
    # Map settings
    default_map_center_lat: float = -25.0
    default_map_center_lon: float = 135.0
    default_map_zoom: int = 4


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    log_directory: str = "logs"
    max_log_size_mb: int = 100
    backup_count: int = 5
    
    # Log to console
    console_logging: bool = True
    
    # Log format
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class SystemConfig:
    """Complete system configuration."""
    database: DatabaseConfig
    processing: ProcessingConfig
    dashboard: DashboardConfig
    logging: LoggingConfig
    s3: S3Config = field(default_factory=S3Config)
    usgs: USGSConfig = field(default_factory=USGSConfig)
    
    # Environment settings
    environment: str = "development"  # development, staging, production
    debug: bool = True
    
    # Security
    secret_key: str = "change-this-in-production"


class ConfigManager:
    """Manages application configuration from various sources."""
    
    def __init__(self, config_file: str = None, env_file: str = ".env"):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to JSON configuration file
            env_file: Path to environment variables file
        """
        self.config_file = config_file
        self.env_file = env_file
        self._config = None
        
        # Load environment variables
        if os.path.exists(env_file):
            load_dotenv(env_file)
            logger.info(f"Loaded environment variables from {env_file}")
        
        self._load_config()
    
    def _load_config(self):
        """Load configuration from all sources."""
        # Start with default configuration
        config_dict = self._get_default_config()
        
        # Override with file configuration if exists
        if self.config_file and os.path.exists(self.config_file):
            file_config = self._load_from_file(self.config_file)
            config_dict = self._merge_configs(config_dict, file_config)
            logger.info(f"Loaded configuration from {self.config_file}")
        
        # Override with environment variables
        env_config = self._load_from_environment()
        config_dict = self._merge_configs(config_dict, env_config)
        
        # Create config object
        self._config = SystemConfig(
            database=DatabaseConfig(**config_dict.get('database', {})),
            processing=ProcessingConfig(**config_dict.get('processing', {})),
            dashboard=DashboardConfig(**config_dict.get('dashboard', {})),
            logging=LoggingConfig(**config_dict.get('logging', {})),
            s3=S3Config(**config_dict.get('s3', {})),
            usgs=USGSConfig(**config_dict.get('usgs', {})),
            environment=config_dict.get('environment', 'development'),
            debug=config_dict.get('debug', True),
            secret_key=config_dict.get('secret_key', 'change-this-in-production')
        )
        
        logger.info(f"Configuration loaded for environment: {self._config.environment}")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration values."""
        return {
            'database': asdict(DatabaseConfig()),
            'processing': asdict(ProcessingConfig()),
            'dashboard': asdict(DashboardConfig()),
            'logging': asdict(LoggingConfig()),
            'environment': 'development',
            'debug': True,
            'secret_key': 'change-this-in-production'
        }
    
    def _load_from_file(self, file_path: str) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config file {file_path}: {e}")
            return {}
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        env_config = {}
        
        # Database configuration
        if any(var in os.environ for var in ['DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME', 'DATABASE_URL']):
            env_config['database'] = {}
            
            if 'DATABASE_URL' in os.environ:
                # Parse full database URL if provided
                pass  # URL will be used directly
            else:
                # Individual database parameters
                if 'DB_HOST' in os.environ:
                    env_config['database']['host'] = os.environ['DB_HOST']
                if 'DB_PORT' in os.environ:
                    env_config['database']['port'] = int(os.environ['DB_PORT'])
                if 'DB_USER' in os.environ:
                    env_config['database']['username'] = os.environ['DB_USER']
                if 'DB_PASSWORD' in os.environ:
                    env_config['database']['password'] = os.environ['DB_PASSWORD']
                if 'DB_NAME' in os.environ:
                    env_config['database']['database'] = os.environ['DB_NAME']
        
        # Processing configuration
        processing_env = {}
        if 'CONFIDENCE_THRESHOLD' in os.environ:
            processing_env['confidence_threshold'] = float(os.environ['CONFIDENCE_THRESHOLD'])
        if 'MAX_CONCURRENT_JOBS' in os.environ:
            processing_env['max_concurrent_jobs'] = int(os.environ['MAX_CONCURRENT_JOBS'])
        if 'OUTPUT_DIRECTORY' in os.environ:
            processing_env['output_directory'] = os.environ['OUTPUT_DIRECTORY']
        if 'ENABLE_SCHEDULER' in os.environ:
            processing_env['enable_scheduler'] = os.environ['ENABLE_SCHEDULER'].lower() == 'true'
        
        if processing_env:
            env_config['processing'] = processing_env
        
        # Dashboard configuration
        dashboard_env = {}
        if 'DASHBOARD_HOST' in os.environ:
            dashboard_env['host'] = os.environ['DASHBOARD_HOST']
        if 'DASHBOARD_PORT' in os.environ:
            dashboard_env['port'] = int(os.environ['DASHBOARD_PORT'])
        if 'DASHBOARD_DEBUG' in os.environ:
            dashboard_env['debug'] = os.environ['DASHBOARD_DEBUG'].lower() == 'true'
        
        if dashboard_env:
            env_config['dashboard'] = dashboard_env

        # S3 configuration
        s3_env = {}
        if 'S3_BUCKET' in os.environ:
            s3_env['bucket'] = os.environ['S3_BUCKET']
        if 'AWS_REGION' in os.environ:
            s3_env['region'] = os.environ['AWS_REGION']
        if 'AWS_PROFILE' in os.environ:
            s3_env['profile'] = os.environ['AWS_PROFILE']
        if 'S3_ENDPOINT_URL' in os.environ:
            s3_env['endpoint_url'] = os.environ['S3_ENDPOINT_URL']
        if 'S3_ROLE_ARN' in os.environ:
            s3_env['role_arn'] = os.environ['S3_ROLE_ARN']
        if 'S3_BASE_PREFIX' in os.environ:
            s3_env['base_prefix'] = os.environ['S3_BASE_PREFIX']
        if s3_env:
            env_config['s3'] = s3_env

        # USGS M2M configuration
        usgs_env = {}
        if 'USGS_USERNAME' in os.environ:
            usgs_env['username'] = os.environ['USGS_USERNAME']
        if 'USGS_PASSWORD' in os.environ:
            usgs_env['password'] = os.environ['USGS_PASSWORD']
        if 'USGS_TOKEN' in os.environ:
            usgs_env['token'] = os.environ['USGS_TOKEN']
        if 'USGS_M2M_ENDPOINT' in os.environ:
            usgs_env['endpoint'] = os.environ['USGS_M2M_ENDPOINT']
        if 'USGS_DATASET' in os.environ:
            usgs_env['dataset'] = os.environ['USGS_DATASET']
        if 'USGS_NODE' in os.environ:
            usgs_env['node'] = os.environ['USGS_NODE']
        if usgs_env:
            env_config['usgs'] = usgs_env
        
        # Logging configuration
        logging_env = {}
        if 'LOG_LEVEL' in os.environ:
            logging_env['level'] = os.environ['LOG_LEVEL'].upper()
        if 'LOG_DIRECTORY' in os.environ:
            logging_env['log_directory'] = os.environ['LOG_DIRECTORY']
        
        if logging_env:
            env_config['logging'] = logging_env
        
        # System configuration
        if 'ENVIRONMENT' in os.environ:
            env_config['environment'] = os.environ['ENVIRONMENT']
        if 'DEBUG' in os.environ:
            env_config['debug'] = os.environ['DEBUG'].lower() == 'true'
        if 'SECRET_KEY' in os.environ:
            env_config['secret_key'] = os.environ['SECRET_KEY']
        
        return env_config
    
    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Merge two configuration dictionaries."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        
        return result
    
    @property
    def config(self) -> SystemConfig:
        """Get the current configuration."""
        return self._config
    
    def get_database_url(self) -> str:
        """Get the database connection URL."""
        # Check for direct DATABASE_URL environment variable first
        if 'DATABASE_URL' in os.environ:
            return os.environ['DATABASE_URL']
        return self._config.database.connection_url
    
    def save_config(self, file_path: str):
        """Save current configuration to a file."""
        try:
            config_dict = {
                'database': asdict(self._config.database),
                'processing': asdict(self._config.processing),
                'dashboard': asdict(self._config.dashboard),
                'logging': asdict(self._config.logging),
                's3': asdict(self._config.s3),
                'usgs': asdict(self._config.usgs),
                'environment': self._config.environment,
                'debug': self._config.debug,
                'secret_key': self._config.secret_key
            }
            
            with open(file_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
            
            logger.info(f"Configuration saved to {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to save config to {file_path}: {e}")
            raise
    
    def validate_config(self) -> bool:
        """Validate the current configuration."""
        try:
            # Check database configuration
            if not all([
                self._config.database.host,
                self._config.database.username,
                self._config.database.password,
                self._config.database.database
            ]):
                logger.error("Database configuration is incomplete")
                return False
            
            # Check processing configuration
            if self._config.processing.confidence_threshold < 0 or self._config.processing.confidence_threshold > 1:
                logger.error("Confidence threshold must be between 0 and 1")
                return False
            
            if self._config.processing.max_concurrent_jobs < 1:
                logger.error("Max concurrent jobs must be at least 1")
                return False
            
            # Check dashboard configuration
            if self._config.dashboard.port < 1 or self._config.dashboard.port > 65535:
                logger.error("Dashboard port must be between 1 and 65535")
                return False
            
            # Create output directories if they don't exist
            os.makedirs(self._config.processing.output_directory, exist_ok=True)
            os.makedirs(self._config.logging.log_directory, exist_ok=True)
            
            logger.info("Configuration validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return False


# Global configuration manager instance
config_manager = ConfigManager()


def get_config() -> SystemConfig:
    """Get the current system configuration."""
    return config_manager.config


def get_database_url() -> str:
    """Get the database connection URL."""
    return config_manager.get_database_url()


def load_config(config_file: str = None, env_file: str = ".env") -> SystemConfig:
    """Load configuration from specified sources."""
    global config_manager
    config_manager = ConfigManager(config_file, env_file)
    return config_manager.config


def validate_config() -> bool:
    """Validate the current configuration."""
    return config_manager.validate_config()