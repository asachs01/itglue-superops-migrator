"""Progress tracking and reporting for migration."""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from migrator.logging import get_logger


class ProgressTracker:
    """Track and report migration progress."""

    def __init__(self, console: Optional[Console] = None) -> None:
        """Initialize progress tracker.

        Args:
            console: Rich console for output
        """
        self.console = console or Console()
        self.logger = get_logger("progress_tracker")
        
        # Progress state
        self.total_items = 0
        self.completed_items = 0
        self.failed_items = 0
        self.skipped_items = 0
        self.start_time: Optional[float] = None
        self.last_update_time: Optional[float] = None
        
        # Progress tracking
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
        )
        self.main_task: Optional[TaskID] = None
        self.live: Optional[Live] = None
        
        # Statistics
        self.document_times: List[float] = []
        self.attachment_counts: List[int] = []
        self.error_counts: Dict[str, int] = {}
        self.category_counts: Dict[str, int] = {}
        
        # Progress persistence
        self.checkpoint_file = Path("migration_progress.json")
        self.checkpoint_interval = 60  # Save every 60 seconds
        self.last_checkpoint_time = 0

    def initialize(self, total_items: int) -> None:
        """Initialize progress tracking.

        Args:
            total_items: Total number of items to process
        """
        self.total_items = total_items
        self.completed_items = 0
        self.failed_items = 0
        self.skipped_items = 0
        self.start_time = time.monotonic()
        self.last_update_time = self.start_time
        
        # Start progress display
        self.main_task = self.progress.add_task(
            "Migrating documents...",
            total=total_items,
        )
        
        # Start live display
        self.live = Live(self._create_display(), console=self.console, refresh_per_second=1)
        self.live.start()
        
        self.logger.info(
            "progress_initialized",
            total_items=total_items,
        )

    def update(
        self,
        completed: int,
        failed: int = 0,
        skipped: int = 0,
        document_time: Optional[float] = None,
        attachment_count: int = 0,
    ) -> None:
        """Update progress.

        Args:
            completed: Number of completed items
            failed: Number of failed items
            skipped: Number of skipped items
            document_time: Time taken for last document
            attachment_count: Number of attachments in last document
        """
        self.completed_items = completed
        self.failed_items = failed
        self.skipped_items = skipped
        self.last_update_time = time.monotonic()
        
        # Update progress bar
        if self.main_task is not None:
            self.progress.update(
                self.main_task,
                completed=completed + failed + skipped,
            )
        
        # Track statistics
        if document_time:
            self.document_times.append(document_time)
        if attachment_count > 0:
            self.attachment_counts.append(attachment_count)
        
        # Update live display
        if self.live:
            self.live.update(self._create_display())
        
        # Save checkpoint if needed
        if self.last_update_time - self.last_checkpoint_time > self.checkpoint_interval:
            self.save_checkpoint()

    def update_category(self, category: str) -> None:
        """Update category count.

        Args:
            category: Category name
        """
        self.category_counts[category] = self.category_counts.get(category, 0) + 1

    def update_error(self, error_type: str) -> None:
        """Update error count.

        Args:
            error_type: Type of error
        """
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

    def get_eta(self) -> Optional[datetime]:
        """Calculate estimated time of completion.

        Returns:
            ETA datetime or None
        """
        if not self.start_time or not self.document_times:
            return None
        
        # Calculate average time per document
        avg_time = sum(self.document_times) / len(self.document_times)
        
        # Calculate remaining items
        processed = self.completed_items + self.failed_items + self.skipped_items
        remaining = self.total_items - processed
        
        if remaining <= 0:
            return None
        
        # Calculate ETA
        eta_seconds = remaining * avg_time
        return datetime.now() + timedelta(seconds=eta_seconds)

    def get_rate(self) -> float:
        """Calculate processing rate.

        Returns:
            Documents per minute
        """
        if not self.start_time:
            return 0.0
        
        elapsed = time.monotonic() - self.start_time
        if elapsed < 1:
            return 0.0
        
        processed = self.completed_items + self.failed_items + self.skipped_items
        return (processed / elapsed) * 60  # Convert to per minute

    def _create_display(self) -> Panel:
        """Create rich display panel.

        Returns:
            Display panel
        """
        # Create statistics table
        stats_table = Table(show_header=False, box=None)
        stats_table.add_column("Label", style="cyan")
        stats_table.add_column("Value", style="green")
        
        # Calculate statistics
        processed = self.completed_items + self.failed_items + self.skipped_items
        progress_pct = (processed / self.total_items * 100) if self.total_items > 0 else 0
        rate = self.get_rate()
        eta = self.get_eta()
        
        # Add rows
        stats_table.add_row("Total Documents", str(self.total_items))
        stats_table.add_row("Completed", f"{self.completed_items} ✓")
        stats_table.add_row("Failed", f"{self.failed_items} ✗" if self.failed_items > 0 else "0")
        stats_table.add_row("Skipped", f"{self.skipped_items} ⊘" if self.skipped_items > 0 else "0")
        stats_table.add_row("Progress", f"{progress_pct:.1f}%")
        stats_table.add_row("Rate", f"{rate:.1f} docs/min")
        
        if eta:
            stats_table.add_row("ETA", eta.strftime("%H:%M:%S"))
        
        if self.attachment_counts:
            avg_attachments = sum(self.attachment_counts) / len(self.attachment_counts)
            stats_table.add_row("Avg Attachments", f"{avg_attachments:.1f}")
        
        # Create main display
        display = Table.grid()
        display.add_column()
        display.add_row(self.progress)
        display.add_row("")
        display.add_row(stats_table)
        
        # Add error summary if there are errors
        if self.error_counts:
            error_table = Table(title="Errors", show_header=False, box=None)
            error_table.add_column("Type", style="yellow")
            error_table.add_column("Count", style="red")
            
            for error_type, count in sorted(self.error_counts.items()):
                error_table.add_row(error_type, str(count))
            
            display.add_row("")
            display.add_row(error_table)
        
        return Panel(display, title="Migration Progress", border_style="blue")

    def save_checkpoint(self) -> None:
        """Save progress checkpoint to file."""
        checkpoint = {
            "timestamp": datetime.now().isoformat(),
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "failed_items": self.failed_items,
            "skipped_items": self.skipped_items,
            "start_time": self.start_time,
            "document_times": self.document_times[-100:],  # Keep last 100
            "attachment_counts": self.attachment_counts[-100:],
            "error_counts": self.error_counts,
            "category_counts": self.category_counts,
        }
        
        try:
            with open(self.checkpoint_file, "w") as f:
                json.dump(checkpoint, f, indent=2)
            
            self.last_checkpoint_time = time.monotonic()
            
            self.logger.debug(
                "checkpoint_saved",
                completed=self.completed_items,
                failed=self.failed_items,
            )
        except Exception as e:
            self.logger.error(
                "checkpoint_save_failed",
                error=str(e),
            )

    def load_checkpoint(self) -> bool:
        """Load progress checkpoint from file.

        Returns:
            True if checkpoint loaded successfully
        """
        if not self.checkpoint_file.exists():
            return False
        
        try:
            with open(self.checkpoint_file, "r") as f:
                checkpoint = json.load(f)
            
            self.total_items = checkpoint.get("total_items", 0)
            self.completed_items = checkpoint.get("completed_items", 0)
            self.failed_items = checkpoint.get("failed_items", 0)
            self.skipped_items = checkpoint.get("skipped_items", 0)
            self.start_time = checkpoint.get("start_time")
            self.document_times = checkpoint.get("document_times", [])
            self.attachment_counts = checkpoint.get("attachment_counts", [])
            self.error_counts = checkpoint.get("error_counts", {})
            self.category_counts = checkpoint.get("category_counts", {})
            
            self.logger.info(
                "checkpoint_loaded",
                timestamp=checkpoint.get("timestamp"),
                completed=self.completed_items,
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                "checkpoint_load_failed",
                error=str(e),
            )
            return False

    def finish(self) -> Dict[str, Any]:
        """Finish progress tracking and return summary.

        Returns:
            Progress summary
        """
        if self.live:
            self.live.stop()
        
        if not self.start_time:
            return {}
        
        elapsed = time.monotonic() - self.start_time
        processed = self.completed_items + self.failed_items + self.skipped_items
        
        summary = {
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "failed_items": self.failed_items,
            "skipped_items": self.skipped_items,
            "success_rate": (self.completed_items / processed * 100) if processed > 0 else 0,
            "elapsed_time": elapsed,
            "average_time_per_document": elapsed / processed if processed > 0 else 0,
            "processing_rate": (processed / elapsed) * 60 if elapsed > 0 else 0,
            "total_attachments": sum(self.attachment_counts),
            "average_attachments": sum(self.attachment_counts) / len(self.attachment_counts) if self.attachment_counts else 0,
            "error_counts": self.error_counts,
            "category_distribution": self.category_counts,
        }
        
        # Clean up checkpoint file
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
        
        self.logger.info(
            "progress_finished",
            **summary,
        )
        
        return summary

    def generate_report(self, output_path: Optional[Path] = None) -> str:
        """Generate detailed progress report.

        Args:
            output_path: Optional path to save report

        Returns:
            Report content
        """
        if not self.start_time:
            return "No migration data available"
        
        elapsed = time.monotonic() - self.start_time
        processed = self.completed_items + self.failed_items + self.skipped_items
        
        # Build report
        report_lines = [
            "=" * 60,
            "MIGRATION PROGRESS REPORT",
            "=" * 60,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "SUMMARY",
            "-" * 30,
            f"Total Documents: {self.total_items}",
            f"Processed: {processed} ({processed/self.total_items*100:.1f}%)",
            f"  - Completed: {self.completed_items}",
            f"  - Failed: {self.failed_items}",
            f"  - Skipped: {self.skipped_items}",
            "",
            "PERFORMANCE",
            "-" * 30,
            f"Elapsed Time: {timedelta(seconds=int(elapsed))}",
            f"Average Time per Document: {elapsed/processed:.2f}s" if processed > 0 else "N/A",
            f"Processing Rate: {(processed/elapsed)*60:.1f} docs/min" if elapsed > 0 else "N/A",
            "",
        ]
        
        # Add attachment statistics
        if self.attachment_counts:
            report_lines.extend([
                "ATTACHMENTS",
                "-" * 30,
                f"Total Attachments: {sum(self.attachment_counts)}",
                f"Average per Document: {sum(self.attachment_counts)/len(self.attachment_counts):.1f}",
                f"Max Attachments: {max(self.attachment_counts)}",
                "",
            ])
        
        # Add category distribution
        if self.category_counts:
            report_lines.extend([
                "CATEGORY DISTRIBUTION",
                "-" * 30,
            ])
            for category, count in sorted(self.category_counts.items(), key=lambda x: x[1], reverse=True):
                report_lines.append(f"  {category}: {count}")
            report_lines.append("")
        
        # Add error summary
        if self.error_counts:
            report_lines.extend([
                "ERROR SUMMARY",
                "-" * 30,
            ])
            for error_type, count in sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True):
                report_lines.append(f"  {error_type}: {count}")
            report_lines.append("")
        
        # Add ETA if migration is ongoing
        if processed < self.total_items:
            eta = self.get_eta()
            if eta:
                report_lines.extend([
                    "ESTIMATED COMPLETION",
                    "-" * 30,
                    f"ETA: {eta.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Remaining: {self.total_items - processed} documents",
                    "",
                ])
        
        report_lines.append("=" * 60)
        
        report = "\n".join(report_lines)
        
        # Save to file if path provided
        if output_path:
            output_path.write_text(report)
            self.logger.info("report_saved", path=str(output_path))
        
        return report