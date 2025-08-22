"""Migration orchestrator for ITGlue to SuperOps migration."""

import asyncio
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from migrator.api.graphql_client import SuperOpsGraphQLClient
from migrator.api.rest_client import SuperOpsAttachmentClient
from migrator.config import Config
from migrator.core.database import (
    Attachment,
    AttachmentStatus,
    Database,
    Document,
    DocumentStatus,
    MigrationRun,
)
from migrator.logging import logger
from migrator.parsers.csv_parser import CSVMetadataParser, DocumentMetadata
from migrator.parsers.html_parser import ITGlueDocumentParser
from migrator.transformers.content_transformer import ContentTransformer
from migrator.utils.progress import ProgressTracker
from migrator.utils.errors import ErrorHandler, MigrationError


class MigrationOrchestrator:
    """Orchestrates the entire migration process."""

    def __init__(self, config: Config) -> None:
        """Initialize the orchestrator.

        Args:
            config: Migration configuration
        """
        self.config = config
        self.logger = logger.get_logger("orchestrator")
        
        # Initialize components
        self.database = Database(config.database.path, config.database.connection_timeout)
        self.csv_parser = CSVMetadataParser(config.source.documents_path)
        self.html_parser = ITGlueDocumentParser()
        self.content_transformer = ContentTransformer(config.source.attachments_path)
        self.progress_tracker = ProgressTracker()
        self.error_handler = ErrorHandler(config.migration.continue_on_error)
        
        # API clients (initialized in async context)
        self.graphql_client: Optional[SuperOpsGraphQLClient] = None
        self.attachment_client: Optional[SuperOpsAttachmentClient] = None
        
        # Runtime state
        self.current_run: Optional[MigrationRun] = None
        self.metadata_cache: Dict[str, DocumentMetadata] = {}
        self.category_cache: Dict[str, str] = {}  # name -> id
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize the orchestrator and its components."""
        self.logger.info("initializing_orchestrator")
        
        # Initialize database
        await self.database.initialize()
        
        # Parse CSV metadata
        self.metadata_cache = self.csv_parser.parse_csv(self.config.source.csv_path)
        
        # Initialize API clients
        self.graphql_client = SuperOpsGraphQLClient(self.config.superops)
        self.attachment_client = SuperOpsAttachmentClient(
            self.config.superops,
            self.config.migration.max_attachment_size,
        )
        
        # Set attachment client in transformer
        self.content_transformer.set_attachment_client(self.attachment_client)
        
        # Log statistics
        stats = self.csv_parser.get_statistics()
        self.logger.info(
            "metadata_loaded",
            total_documents=stats["total_documents"],
            organizations=stats["organizations"],
            documents_with_files=stats["documents_with_files"],
        )

    async def migrate(
        self,
        resume: bool = False,
        limit: Optional[int] = None,
        filter_pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the migration process.

        Args:
            resume: Whether to resume from last checkpoint
            limit: Maximum number of documents to migrate
            filter_pattern: Regex pattern to filter documents

        Returns:
            Migration statistics
        """
        start_time = time.monotonic()
        
        try:
            # Initialize components
            await self.initialize()
            
            # Configure logging
            logger.configure(self.config.logging)
            
            # Test API connectivity
            async with self.graphql_client, self.attachment_client:
                if not await self.graphql_client.test_connection():
                    raise MigrationError("Failed to connect to SuperOps API")
                
                # Create or resume migration run
                if resume:
                    self.current_run = await self._resume_migration()
                else:
                    self.current_run = await self._create_migration_run()
                
                # Get documents to migrate
                documents = await self._get_documents_to_migrate(
                    resume, limit, filter_pattern
                )
                
                if not documents:
                    self.logger.info("no_documents_to_migrate")
                    return {"status": "completed", "documents_processed": 0}
                
                # Log migration start
                logger.log_migration_start(
                    len(documents),
                    self.config.model_dump(exclude={"superops": {"api_token"}}),
                )
                
                # Initialize progress tracking
                self.progress_tracker.initialize(len(documents))
                
                # Process documents in batches
                await self._process_documents(documents)
                
                # Finalize migration
                await self._finalize_migration()
                
                # Calculate statistics
                duration = time.monotonic() - start_time
                stats = await self._get_migration_stats()
                
                # Log completion
                logger.log_migration_complete(
                    stats["total_documents"],
                    stats["successful_documents"],
                    stats["failed_documents"],
                    duration,
                )
                
                return {
                    "status": "completed",
                    "duration_seconds": duration,
                    **stats,
                }
                
        except asyncio.CancelledError:
            self.logger.warning("migration_cancelled")
            await self._handle_cancellation()
            raise
            
        except Exception as e:
            self.logger.error(
                "migration_failed",
                error=str(e),
                exc_info=e,
            )
            if self.current_run:
                self.current_run.error_log.append(str(e))
                await self.database.update_migration_run(self.current_run)
            raise

    async def _create_migration_run(self) -> MigrationRun:
        """Create a new migration run.

        Returns:
            Created migration run
        """
        # Count total documents
        total_documents = len(self.metadata_cache)
        
        # Convert Path objects to strings for JSON serialization
        config_dict = self.config.model_dump(exclude={"superops": {"api_token"}})
        
        def convert_paths(obj: Any) -> Any:
            """Convert Path objects to strings recursively."""
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_paths(item) for item in obj]
            elif isinstance(obj, Path):
                return str(obj)
            return obj
        
        config_dict = convert_paths(config_dict)
        
        # Create run in database
        run = await self.database.create_migration_run(
            total_documents,
            config_dict,
        )
        
        # Add all documents to database
        for locator, metadata in self.metadata_cache.items():
            document = Document(
                id=locator,
                title=metadata.name,
                organization=metadata.organization,
                status=DocumentStatus.PENDING,
                metadata={
                    "owner": metadata.owner,
                    "publisher": metadata.publisher,
                    "public": metadata.public,
                    "archived": metadata.archived,
                },
            )
            await self.database.add_document(run.id, document)
        
        self.logger.info(
            "migration_run_created",
            run_id=run.id,
            total_documents=total_documents,
        )
        
        return run

    async def _resume_migration(self) -> MigrationRun:
        """Resume from last migration run.

        Returns:
            Resumed migration run

        Raises:
            MigrationError: If no run to resume
        """
        run = await self.database.get_latest_migration_run()
        
        if not run:
            raise MigrationError("No migration run to resume")
        
        if run.completed_at:
            raise MigrationError("Last migration run is already completed")
        
        self.logger.info(
            "resuming_migration",
            run_id=run.id,
            completed=run.successful_documents + run.failed_documents + run.skipped_documents,
            remaining=run.total_documents - (run.successful_documents + run.failed_documents + run.skipped_documents),
        )
        
        return run

    async def _get_documents_to_migrate(
        self,
        resume: bool,
        limit: Optional[int],
        filter_pattern: Optional[str],
    ) -> List[Document]:
        """Get list of documents to migrate.

        Args:
            resume: Whether resuming migration
            limit: Maximum number of documents
            filter_pattern: Filter pattern

        Returns:
            List of documents to migrate
        """
        if not self.current_run:
            raise RuntimeError("No current migration run")
        
        # Get pending documents from database
        documents = await self.database.get_documents_by_status(
            self.current_run.id,
            DocumentStatus.PENDING,
        )
        
        # Apply filter if specified
        if filter_pattern:
            pattern = re.compile(filter_pattern, re.IGNORECASE)
            documents = [
                doc for doc in documents
                if pattern.search(doc.title) or pattern.search(doc.organization)
            ]
        
        # Apply limit if specified
        if limit:
            documents = documents[:limit]
        
        # Sort by migration order
        migration_order = self.csv_parser.get_migration_order()
        order_map = {loc: i for i, loc in enumerate(migration_order)}
        documents.sort(key=lambda d: order_map.get(d.id, len(order_map)))
        
        return documents

    async def _process_documents(self, documents: List[Document]) -> None:
        """Process documents in batches.

        Args:
            documents: Documents to process
        """
        batch_size = self.config.migration.batch_size
        total_batches = (len(documents) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(documents))
            batch = documents[start_idx:end_idx]
            
            self.logger.info(
                "processing_batch",
                batch_num=batch_num + 1,
                total_batches=total_batches,
                batch_size=len(batch),
            )
            
            # Process batch concurrently
            tasks = [self._process_document(doc) for doc in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle results
            for doc, result in zip(batch, results):
                if isinstance(result, Exception):
                    await self._handle_document_error(doc, result)
                
            # Check for shutdown
            if self._shutdown_event.is_set():
                self.logger.info("shutdown_requested")
                break
            
            # Update progress
            self.progress_tracker.update(end_idx)
            
            # Small delay between batches to avoid overwhelming API
            if batch_num < total_batches - 1:
                await asyncio.sleep(1)

    async def _process_document(self, document: Document) -> None:
        """Process a single document.

        Args:
            document: Document to process
        """
        start_time = time.monotonic()
        
        try:
            # Update status to in-progress
            await self.database.update_document_status(
                document.id,
                DocumentStatus.IN_PROGRESS,
            )
            
            # Get metadata
            metadata = self.metadata_cache.get(document.id)
            if not metadata:
                raise MigrationError(f"Metadata not found for document {document.id}")
            
            # Check if file exists
            if not metadata.file_path or not metadata.file_path.exists():
                self.logger.warning(
                    "document_file_not_found",
                    document_id=document.id,
                    title=document.title,
                )
                await self.database.update_document_status(
                    document.id,
                    DocumentStatus.SKIPPED,
                    error_message="File not found",
                )
                return
            
            # Check if document should be skipped
            if self.config.migration.skip_existing:
                existing_id = await self.graphql_client.check_article_exists(document.title)
                if existing_id:
                    self.logger.info(
                        "document_already_exists",
                        document_id=document.id,
                        title=document.title,
                        superops_id=existing_id,
                    )
                    await self.database.update_document_status(
                        document.id,
                        DocumentStatus.SKIPPED,
                        superops_id=existing_id,
                        error_message="Already exists",
                    )
                    return
            
            # Parse HTML document
            parsed_doc = self.html_parser.parse_document(metadata.file_path)
            
            # Validate parsed document
            validation_errors = self.html_parser.validate_document(parsed_doc)
            if validation_errors and not self.config.migration.continue_on_error:
                raise MigrationError(f"Validation errors: {', '.join(validation_errors)}")
            
            # Transform content
            transformed = self.content_transformer.transform_document(
                parsed_doc,
                metadata.organization,
            )
            
            # Check transformation errors
            if transformed.validation_errors and not self.config.migration.continue_on_error:
                raise MigrationError(f"Transformation errors: {', '.join(transformed.validation_errors)}")
            
            # Upload attachments
            if transformed.attachments and not self.config.migration.dry_run:
                await self._upload_attachments(document.id, transformed.attachments)
                
                # Update content with attachment URLs
                url_map = await self.content_transformer.upload_attachments(transformed.attachments)
                transformed.content_html = self.content_transformer._update_image_references(
                    transformed.content_html,
                    transformed.attachments,
                )
            
            # Get or create category
            category_id = None
            if transformed.category:
                category_id = await self._get_or_create_category(transformed.category)
            
            # Create article in SuperOps
            if not self.config.migration.dry_run:
                article = await self.graphql_client.create_kb_article(
                    title=transformed.title,
                    content=transformed.content_html,
                    category_id=category_id,
                    tags=transformed.tags,
                    metadata=transformed.metadata,
                )
                
                superops_id = article.get("itemId")
            else:
                # Dry run - generate fake ID
                superops_id = f"dry-run-{document.id}"
            
            # Update database
            await self.database.update_document_status(
                document.id,
                DocumentStatus.COMPLETED,
                superops_id=superops_id,
            )
            
            # Update run statistics
            if self.current_run:
                self.current_run.successful_documents += 1
                await self.database.update_migration_run(self.current_run)
            
            # Log success
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.log_document_processed(
                document.id,
                document.title,
                "completed",
                duration_ms,
                len(transformed.attachments),
            )
            
        except Exception as e:
            await self._handle_document_error(document, e)
            raise

    async def _upload_attachments(
        self,
        document_id: str,
        attachments: List[Any],
    ) -> None:
        """Upload attachments for a document.

        Args:
            document_id: Document ID
            attachments: List of attachments
        """
        if not self.current_run:
            return
        
        for att in attachments:
            try:
                # Create attachment record
                attachment = Attachment(
                    document_id=document_id,
                    filename=att.filename,
                    file_path=att.original_path,
                    size_bytes=att.size_bytes,
                    mime_type=att.mime_type,
                    status=AttachmentStatus.PENDING,
                )
                
                attachment = await self.database.add_attachment(
                    self.current_run.id,
                    attachment,
                )
                
                # Upload if needed
                if att.needs_upload and not att.superops_url:
                    if att.is_embedded and att.base64_data:
                        result = await self.attachment_client.upload_base64_image(
                            att.base64_data,
                            att.filename,
                            att.mime_type or "image/png",
                        )
                    else:
                        file_path = Path(att.original_path)
                        if file_path.exists():
                            result = await self.attachment_client.upload_file(file_path)
                        else:
                            raise FileNotFoundError(f"Attachment not found: {file_path}")
                    
                    if result.success:
                        await self.database.update_attachment_status(
                            attachment.id,
                            AttachmentStatus.UPLOADED,
                            superops_url=result.url,
                        )
                        att.superops_url = result.url
                        self.current_run.successful_attachments += 1
                    else:
                        await self.database.update_attachment_status(
                            attachment.id,
                            AttachmentStatus.FAILED,
                            error_message=result.error,
                        )
                        self.current_run.failed_attachments += 1
                
                elif att.superops_url:
                    # Already uploaded
                    await self.database.update_attachment_status(
                        attachment.id,
                        AttachmentStatus.UPLOADED,
                        superops_url=att.superops_url,
                    )
                    self.current_run.successful_attachments += 1
                
            except Exception as e:
                self.logger.error(
                    "attachment_upload_error",
                    document_id=document_id,
                    filename=att.filename,
                    error=str(e),
                )
                
                if attachment and attachment.id:
                    await self.database.update_attachment_status(
                        attachment.id,
                        AttachmentStatus.FAILED,
                        error_message=str(e),
                    )
                
                if self.current_run:
                    self.current_run.failed_attachments += 1

    async def _get_or_create_category(self, category_name: str) -> str:
        """Get or create a category in SuperOps.

        Args:
            category_name: Category name

        Returns:
            Category ID
        """
        # Check cache
        if category_name in self.category_cache:
            return self.category_cache[category_name]
        
        # Get or create via API
        category_id = await self.graphql_client.get_or_create_category(category_name)
        
        # Update cache
        self.category_cache[category_name] = category_id
        
        return category_id

    async def _handle_document_error(self, document: Document, error: Exception) -> None:
        """Handle error during document processing.

        Args:
            document: Document that failed
            error: Exception that occurred
        """
        error_message = str(error)
        
        self.logger.error(
            "document_processing_failed",
            document_id=document.id,
            title=document.title,
            error=error_message,
            exc_info=error,
        )
        
        # Update document status
        await self.database.update_document_status(
            document.id,
            DocumentStatus.FAILED,
            error_message=error_message,
        )
        
        # Update run statistics
        if self.current_run:
            self.current_run.failed_documents += 1
            self.current_run.error_log.append(f"{document.id}: {error_message}")
            await self.database.update_migration_run(self.current_run)
        
        # Log error
        logger.log_document_processed(
            document.id,
            document.title,
            "failed",
            0,
            0,
        )
        
        # Decide whether to continue
        if not self.config.migration.continue_on_error:
            self.logger.error("stopping_on_error")
            self._shutdown_event.set()

    async def _finalize_migration(self) -> None:
        """Finalize the migration run."""
        if not self.current_run:
            return
        
        # Mark run as completed
        self.current_run.completed_at = datetime.utcnow()
        await self.database.update_migration_run(self.current_run)
        
        # Generate final report
        stats = await self.database.get_statistics(self.current_run.id)
        
        self.logger.info(
            "migration_finalized",
            run_id=self.current_run.id,
            statistics=stats,
        )

    async def _handle_cancellation(self) -> None:
        """Handle migration cancellation."""
        if self.current_run:
            # Update any in-progress documents
            in_progress = await self.database.get_documents_by_status(
                self.current_run.id,
                DocumentStatus.IN_PROGRESS,
            )
            
            for doc in in_progress:
                await self.database.update_document_status(
                    doc.id,
                    DocumentStatus.PENDING,
                )
            
            # Save current state
            await self.database.update_migration_run(self.current_run)
            
            self.logger.info(
                "migration_state_saved",
                run_id=self.current_run.id,
            )

    async def _get_migration_stats(self) -> Dict[str, Any]:
        """Get migration statistics.

        Returns:
            Statistics dictionary
        """
        if not self.current_run:
            return {}
        
        stats = await self.database.get_statistics(self.current_run.id)
        
        return {
            "total_documents": self.current_run.total_documents,
            "successful_documents": self.current_run.successful_documents,
            "failed_documents": self.current_run.failed_documents,
            "skipped_documents": self.current_run.skipped_documents,
            "total_attachments": self.current_run.total_attachments,
            "successful_attachments": self.current_run.successful_attachments,
            "failed_attachments": self.current_run.failed_attachments,
            "document_statistics": stats.get("documents", {}),
            "attachment_statistics": stats.get("attachments", {}),
        }

    def shutdown(self) -> None:
        """Request graceful shutdown."""
        self._shutdown_event.set()