"""ITGlue to SuperOps Migration Tool.

Enterprise-grade tool for migrating ITGlue document exports to SuperOps Knowledge Base.
"""

__version__ = "1.0.0"
__author__ = "DataBridge"

from migrator.config import Config, load_config
from migrator.core.orchestrator import MigrationOrchestrator

__all__ = ["Config", "load_config", "MigrationOrchestrator", "__version__"]