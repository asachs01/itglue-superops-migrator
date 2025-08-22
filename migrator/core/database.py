"""SQLite database management for migration state tracking."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import aiosqlite
from pydantic import BaseModel, Field

from migrator.logging import get_logger


class DocumentStatus(str, Enum):
    """Document migration status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AttachmentStatus(str, Enum):
    """Attachment upload status."""

    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"
    SKIPPED = "skipped"


class MigrationRun(BaseModel):
    """Migration run metadata."""

    id: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_documents: int = 0
    successful_documents: int = 0
    failed_documents: int = 0
    skipped_documents: int = 0
    total_attachments: int = 0
    successful_attachments: int = 0
    failed_attachments: int = 0
    configuration: Dict[str, Any] = Field(default_factory=dict)
    error_log: List[str] = Field(default_factory=list)


class Document(BaseModel):
    """Document record."""

    id: str
    title: str
    organization: str
    status: DocumentStatus = DocumentStatus.PENDING
    superops_id: Optional[str] = None
    error_message: Optional[str] = None
    processed_at: Optional[datetime] = None
    content_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Attachment(BaseModel):
    """Attachment record."""

    id: Optional[int] = None
    document_id: str
    filename: str
    file_path: str
    size_bytes: int
    mime_type: Optional[str] = None
    status: AttachmentStatus = AttachmentStatus.PENDING
    superops_url: Optional[str] = None
    error_message: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    file_hash: Optional[str] = None


class MigrationState:
    """Wrapper for migration state data."""

    def __init__(
        self,
        run: MigrationRun,
        documents: List[Document],
        attachments: List[Attachment],
    ) -> None:
        """Initialize migration state.

        Args:
            run: Current migration run
            documents: List of documents
            attachments: List of attachments
        """
        self.run = run
        self.documents = documents
        self.attachments = attachments
        self.documents_by_id = {doc.id: doc for doc in documents}
        self.attachments_by_doc = self._group_attachments()

    def _group_attachments(self) -> Dict[str, List[Attachment]]:
        """Group attachments by document ID."""
        grouped: Dict[str, List[Attachment]] = {}
        for attachment in self.attachments:
            if attachment.document_id not in grouped:
                grouped[attachment.document_id] = []
            grouped[attachment.document_id].append(attachment)
        return grouped

    def get_pending_documents(self) -> List[Document]:
        """Get all pending documents."""
        return [doc for doc in self.documents if doc.status == DocumentStatus.PENDING]

    def get_failed_documents(self) -> List[Document]:
        """Get all failed documents."""
        return [doc for doc in self.documents if doc.status == DocumentStatus.FAILED]

    def get_document_attachments(self, document_id: str) -> List[Attachment]:
        """Get attachments for a specific document."""
        return self.attachments_by_doc.get(document_id, [])


class Database:
    """SQLite database manager for migration state."""

    def __init__(self, db_path: Path, timeout: int = 30) -> None:
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file
            timeout: Connection timeout in seconds
        """
        self.db_path = db_path
        self.timeout = timeout
        self.logger = get_logger("database")
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize database and create schema if needed."""
        async with self._lock:
            await self._create_schema()
            self.logger.info("database_initialized", path=str(self.db_path))

    async def _create_schema(self) -> None:
        """Create database schema."""
        async with self._get_connection() as conn:
            # Migration runs table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS migration_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    total_documents INTEGER DEFAULT 0,
                    successful_documents INTEGER DEFAULT 0,
                    failed_documents INTEGER DEFAULT 0,
                    skipped_documents INTEGER DEFAULT 0,
                    total_attachments INTEGER DEFAULT 0,
                    successful_attachments INTEGER DEFAULT 0,
                    failed_attachments INTEGER DEFAULT 0,
                    configuration TEXT,
                    error_log TEXT
                )
            """)

            # Documents table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    run_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    organization TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    superops_id TEXT,
                    error_message TEXT,
                    processed_at TIMESTAMP,
                    content_hash TEXT,
                    metadata TEXT,
                    FOREIGN KEY (run_id) REFERENCES migration_runs(id)
                )
            """)

            # Attachments table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mime_type TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    superops_url TEXT,
                    error_message TEXT,
                    uploaded_at TIMESTAMP,
                    file_hash TEXT,
                    FOREIGN KEY (document_id) REFERENCES documents(id),
                    FOREIGN KEY (run_id) REFERENCES migration_runs(id)
                )
            """)

            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_documents_status 
                ON documents(status)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_documents_run 
                ON documents(run_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_document 
                ON attachments(document_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_status 
                ON attachments(status)
            """)

            await conn.commit()

    @asynccontextmanager
    async def _get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get database connection.

        Yields:
            Database connection
        """
        conn = await aiosqlite.connect(
            self.db_path,
            timeout=self.timeout,
        )
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def create_migration_run(
        self,
        total_documents: int,
        configuration: Dict[str, Any],
    ) -> MigrationRun:
        """Create a new migration run.

        Args:
            total_documents: Total number of documents to migrate
            configuration: Migration configuration

        Returns:
            Created migration run
        """
        run = MigrationRun(
            started_at=datetime.utcnow(),
            total_documents=total_documents,
            configuration=configuration,
        )

        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO migration_runs (
                    started_at, total_documents, configuration
                ) VALUES (?, ?, ?)
                """,
                (
                    run.started_at.isoformat(),
                    run.total_documents,
                    json.dumps(run.configuration),
                ),
            )
            run.id = cursor.lastrowid
            await conn.commit()

        self.logger.info(
            "migration_run_created",
            run_id=run.id,
            total_documents=total_documents,
        )
        return run

    async def get_latest_migration_run(self) -> Optional[MigrationRun]:
        """Get the latest migration run.

        Returns:
            Latest migration run or None
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute("""
                SELECT * FROM migration_runs 
                ORDER BY id DESC LIMIT 1
            """)
            row = await cursor.fetchone()

            if not row:
                return None

            return MigrationRun(
                id=row["id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=(
                    datetime.fromisoformat(row["completed_at"])
                    if row["completed_at"]
                    else None
                ),
                total_documents=row["total_documents"],
                successful_documents=row["successful_documents"],
                failed_documents=row["failed_documents"],
                skipped_documents=row["skipped_documents"],
                total_attachments=row["total_attachments"],
                successful_attachments=row["successful_attachments"],
                failed_attachments=row["failed_attachments"],
                configuration=json.loads(row["configuration"] or "{}"),
                error_log=json.loads(row["error_log"] or "[]"),
            )

    async def update_migration_run(self, run: MigrationRun) -> None:
        """Update migration run statistics.

        Args:
            run: Migration run to update
        """
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE migration_runs SET
                    completed_at = ?,
                    successful_documents = ?,
                    failed_documents = ?,
                    skipped_documents = ?,
                    successful_attachments = ?,
                    failed_attachments = ?,
                    error_log = ?
                WHERE id = ?
                """,
                (
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.successful_documents,
                    run.failed_documents,
                    run.skipped_documents,
                    run.successful_attachments,
                    run.failed_attachments,
                    json.dumps(run.error_log),
                    run.id,
                ),
            )
            await conn.commit()

    async def add_document(self, run_id: int, document: Document) -> None:
        """Add a document to the database.

        Args:
            run_id: Migration run ID
            document: Document to add
        """
        async with self._get_connection() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO documents (
                    id, run_id, title, organization, status, 
                    superops_id, error_message, processed_at, 
                    content_hash, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    run_id,
                    document.title,
                    document.organization,
                    document.status.value,
                    document.superops_id,
                    document.error_message,
                    document.processed_at.isoformat() if document.processed_at else None,
                    document.content_hash,
                    json.dumps(document.metadata),
                ),
            )
            await conn.commit()

    async def update_document_status(
        self,
        document_id: str,
        status: DocumentStatus,
        superops_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update document status.

        Args:
            document_id: Document ID
            status: New status
            superops_id: SuperOps KB article ID
            error_message: Error message if failed
        """
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE documents SET 
                    status = ?, 
                    superops_id = ?,
                    error_message = ?,
                    processed_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    superops_id,
                    error_message,
                    datetime.utcnow().isoformat(),
                    document_id,
                ),
            )
            await conn.commit()

        self.logger.debug(
            "document_status_updated",
            document_id=document_id,
            status=status.value,
        )

    async def get_documents_by_status(
        self,
        run_id: int,
        status: DocumentStatus,
    ) -> List[Document]:
        """Get documents by status.

        Args:
            run_id: Migration run ID
            status: Document status

        Returns:
            List of documents
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM documents 
                WHERE run_id = ? AND status = ?
                ORDER BY id
                """,
                (run_id, status.value),
            )
            rows = await cursor.fetchall()

            documents = []
            for row in rows:
                documents.append(
                    Document(
                        id=row["id"],
                        title=row["title"],
                        organization=row["organization"],
                        status=DocumentStatus(row["status"]),
                        superops_id=row["superops_id"],
                        error_message=row["error_message"],
                        processed_at=(
                            datetime.fromisoformat(row["processed_at"])
                            if row["processed_at"]
                            else None
                        ),
                        content_hash=row["content_hash"],
                        metadata=json.loads(row["metadata"] or "{}"),
                    )
                )

            return documents

    async def add_attachment(
        self,
        run_id: int,
        attachment: Attachment,
    ) -> Attachment:
        """Add an attachment to the database.

        Args:
            run_id: Migration run ID
            attachment: Attachment to add

        Returns:
            Attachment with ID
        """
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO attachments (
                    document_id, run_id, filename, file_path, 
                    size_bytes, mime_type, status, superops_url,
                    error_message, uploaded_at, file_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment.document_id,
                    run_id,
                    attachment.filename,
                    attachment.file_path,
                    attachment.size_bytes,
                    attachment.mime_type,
                    attachment.status.value,
                    attachment.superops_url,
                    attachment.error_message,
                    attachment.uploaded_at.isoformat() if attachment.uploaded_at else None,
                    attachment.file_hash,
                ),
            )
            attachment.id = cursor.lastrowid
            await conn.commit()

        return attachment

    async def update_attachment_status(
        self,
        attachment_id: int,
        status: AttachmentStatus,
        superops_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update attachment status.

        Args:
            attachment_id: Attachment ID
            status: New status
            superops_url: SuperOps URL if uploaded
            error_message: Error message if failed
        """
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE attachments SET 
                    status = ?, 
                    superops_url = ?,
                    error_message = ?,
                    uploaded_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    superops_url,
                    error_message,
                    datetime.utcnow().isoformat() if status == AttachmentStatus.UPLOADED else None,
                    attachment_id,
                ),
            )
            await conn.commit()

    async def get_migration_state(self, run_id: int) -> MigrationState:
        """Get complete migration state.

        Args:
            run_id: Migration run ID

        Returns:
            Migration state
        """
        # Get run
        async with self._get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM migration_runs WHERE id = ?",
                (run_id,),
            )
            run_row = await cursor.fetchone()

            if not run_row:
                raise ValueError(f"Migration run {run_id} not found")

            run = MigrationRun(
                id=run_row["id"],
                started_at=datetime.fromisoformat(run_row["started_at"]),
                completed_at=(
                    datetime.fromisoformat(run_row["completed_at"])
                    if run_row["completed_at"]
                    else None
                ),
                total_documents=run_row["total_documents"],
                successful_documents=run_row["successful_documents"],
                failed_documents=run_row["failed_documents"],
                skipped_documents=run_row["skipped_documents"],
                total_attachments=run_row["total_attachments"],
                successful_attachments=run_row["successful_attachments"],
                failed_attachments=run_row["failed_attachments"],
                configuration=json.loads(run_row["configuration"] or "{}"),
                error_log=json.loads(run_row["error_log"] or "[]"),
            )

            # Get documents
            cursor = await conn.execute(
                "SELECT * FROM documents WHERE run_id = ? ORDER BY id",
                (run_id,),
            )
            doc_rows = await cursor.fetchall()

            documents = []
            for row in doc_rows:
                documents.append(
                    Document(
                        id=row["id"],
                        title=row["title"],
                        organization=row["organization"],
                        status=DocumentStatus(row["status"]),
                        superops_id=row["superops_id"],
                        error_message=row["error_message"],
                        processed_at=(
                            datetime.fromisoformat(row["processed_at"])
                            if row["processed_at"]
                            else None
                        ),
                        content_hash=row["content_hash"],
                        metadata=json.loads(row["metadata"] or "{}"),
                    )
                )

            # Get attachments
            cursor = await conn.execute(
                "SELECT * FROM attachments WHERE run_id = ? ORDER BY id",
                (run_id,),
            )
            att_rows = await cursor.fetchall()

            attachments = []
            for row in att_rows:
                attachments.append(
                    Attachment(
                        id=row["id"],
                        document_id=row["document_id"],
                        filename=row["filename"],
                        file_path=row["file_path"],
                        size_bytes=row["size_bytes"],
                        mime_type=row["mime_type"],
                        status=AttachmentStatus(row["status"]),
                        superops_url=row["superops_url"],
                        error_message=row["error_message"],
                        uploaded_at=(
                            datetime.fromisoformat(row["uploaded_at"])
                            if row["uploaded_at"]
                            else None
                        ),
                        file_hash=row["file_hash"],
                    )
                )

        return MigrationState(run, documents, attachments)

    async def get_statistics(self, run_id: int) -> Dict[str, Any]:
        """Get migration statistics.

        Args:
            run_id: Migration run ID

        Returns:
            Statistics dictionary
        """
        async with self._get_connection() as conn:
            # Document statistics
            cursor = await conn.execute(
                """
                SELECT 
                    status,
                    COUNT(*) as count
                FROM documents 
                WHERE run_id = ?
                GROUP BY status
                """,
                (run_id,),
            )
            doc_stats = {row["status"]: row["count"] for row in await cursor.fetchall()}

            # Attachment statistics
            cursor = await conn.execute(
                """
                SELECT 
                    status,
                    COUNT(*) as count,
                    SUM(size_bytes) as total_size
                FROM attachments 
                WHERE run_id = ?
                GROUP BY status
                """,
                (run_id,),
            )
            att_stats = {
                row["status"]: {"count": row["count"], "size": row["total_size"]}
                for row in await cursor.fetchall()
            }

            # Processing time statistics
            cursor = await conn.execute(
                """
                SELECT 
                    MIN(processed_at) as first_processed,
                    MAX(processed_at) as last_processed
                FROM documents 
                WHERE run_id = ? AND processed_at IS NOT NULL
                """,
                (run_id,),
            )
            time_row = await cursor.fetchone()

            return {
                "documents": doc_stats,
                "attachments": att_stats,
                "processing_time": {
                    "first": time_row["first_processed"] if time_row else None,
                    "last": time_row["last_processed"] if time_row else None,
                },
            }

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            self.logger.info("database_closed")