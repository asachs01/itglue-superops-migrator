#!/usr/bin/env python3
"""Migrate all ITGlue documents to the SuperOps staging collection."""

import asyncio
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

from migrator.config import Config
from migrator.parsers.html_parser import ITGlueDocumentParser
from migrator.transformers.content_transformer import ContentTransformer
from migrator.api.graphql_client import SuperOpsGraphQLClient
from migrator.logging import get_logger

# Load environment
load_dotenv()

class BulkStagingMigrator:
    """Handles bulk migration to staging collection."""
    
    def __init__(self, staging_collection_id: str):
        """Initialize the migrator with the staging collection ID."""
        self.staging_collection_id = staging_collection_id
        self.logger = get_logger("bulk_staging")
        self.parser = ITGlueDocumentParser()
        self.attachments_path = Path("export-2/attachments")
        self.transformer = ContentTransformer(attachments_base_path=self.attachments_path)
        
        # Track migration stats
        self.stats = {
            "total": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "errors": []
        }
        
        # Track processed documents
        self.processed_docs = set()
        self.load_processed_docs()
    
    def load_processed_docs(self):
        """Load list of already processed documents."""
        progress_file = Path("migration_progress.json")
        if progress_file.exists():
            with open(progress_file, "r") as f:
                data = json.load(f)
                self.processed_docs = set(data.get("processed", []))
                self.logger.info(f"Loaded {len(self.processed_docs)} previously processed documents")
    
    def save_progress(self):
        """Save migration progress."""
        progress_file = Path("migration_progress.json")
        with open(progress_file, "w") as f:
            json.dump({
                "processed": list(self.processed_docs),
                "stats": self.stats,
                "last_updated": datetime.now().isoformat()
            }, f, indent=2)
    
    async def process_document(
        self, 
        doc_path: Path,
        api_client: SuperOpsGraphQLClient
    ) -> bool:
        """Process a single document."""
        
        doc_id = str(doc_path)
        
        # Skip if already processed
        if doc_id in self.processed_docs:
            self.logger.debug(f"Skipping already processed: {doc_path.name}")
            self.stats["skipped"] += 1
            return True
        
        try:
            # Parse document
            parsed = self.parser.parse_document(doc_path)
            
            # Transform content
            transformed = self.transformer.transform_document(parsed)
            
            # Add source path information
            rel_path = doc_path.relative_to(Path("export-2/documents"))
            path_parts = rel_path.parts[:-1]  # Exclude filename
            
            source_info = {
                "itglue_path": str(rel_path),
                "customer_folder": path_parts[0] if path_parts else "Root",
                "category_folder": path_parts[1] if len(path_parts) > 1 else "Root",
                "full_path": "/".join(path_parts) if path_parts else "Root"
            }
            
            # Add migration header to content
            migration_header = f"""<div style="background-color: #f0f8ff; padding: 12px; margin-bottom: 20px; border-left: 4px solid #0066cc; font-size: 0.9em;">
<strong>📁 Migration Information</strong><br/>
<strong>Source:</strong> ITGlue Export<br/>
<strong>Original Path:</strong> {source_info['full_path']}<br/>
<strong>Customer/Folder:</strong> {source_info['customer_folder']}<br/>
<strong>Category:</strong> {source_info['category_folder']}<br/>
<strong>Migrated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
<em style="color: #666;">This document is in staging and can be moved to its final location.</em>
</div>
<hr style="margin: 20px 0;"/>
"""
            
            # Prepend header to content
            final_content = migration_header + transformed.content_html
            
            # Check if article already exists
            existing_id = await api_client.check_article_exists(transformed.title)
            if existing_id:
                self.logger.info(f"Article already exists: {transformed.title}")
                self.processed_docs.add(doc_id)
                self.stats["skipped"] += 1
                return True
            
            # Create article in staging collection
            article = await api_client.create_kb_article(
                title=transformed.title,
                content=final_content,
                category_id=self.staging_collection_id,
                metadata={
                    "source": "ITGlue",
                    "migration_info": source_info,
                    "original_metadata": transformed.metadata
                }
            )
            
            if article and article.get("itemId"):
                self.logger.info(f"✅ Created: {transformed.title} (ID: {article['itemId']})")
                self.processed_docs.add(doc_id)
                self.stats["success"] += 1
                return True
            else:
                raise Exception("No article ID returned")
                
        except Exception as e:
            self.logger.error(f"Failed to process {doc_path.name}: {e}")
            self.stats["failed"] += 1
            self.stats["errors"].append({
                "file": str(doc_path),
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return False
    
    async def migrate_batch(
        self,
        documents: List[Path],
        api_client: SuperOpsGraphQLClient,
        batch_size: int = 10
    ):
        """Migrate documents in batches."""
        
        total = len(documents)
        self.stats["total"] = total
        
        print(f"\n📚 Starting migration of {total} documents to staging")
        print(f"📁 Staging Collection ID: {self.staging_collection_id}")
        print("="*60)
        
        for i in range(0, total, batch_size):
            batch = documents[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            print(f"\n📦 Batch {batch_num}/{total_batches} ({len(batch)} documents)")
            print("-"*40)
            
            for doc_path in batch:
                # Show progress
                current = i + batch.index(doc_path) + 1
                progress = (current / total) * 100
                print(f"[{current}/{total}] ({progress:.1f}%) Processing: {doc_path.name[:50]}...")
                
                # Process document
                success = await self.process_document(doc_path, api_client)
                
                # Save progress after each document
                if current % 5 == 0:  # Save every 5 documents
                    self.save_progress()
                
                # Small delay to respect rate limits
                await asyncio.sleep(0.1)
            
            # Save progress after each batch
            self.save_progress()
            
            # Show batch stats
            print(f"\nBatch {batch_num} complete: ✅ {self.stats['success']} | ⏭️ {self.stats['skipped']} | ❌ {self.stats['failed']}")
            
            # Delay between batches
            if i + batch_size < total:
                print("Waiting 2 seconds before next batch...")
                await asyncio.sleep(2)

async def main():
    """Main migration function."""
    
    # Configuration
    STAGING_COLLECTION_ID = "2540036476765265920"  # Your staging collection
    
    # Setup
    logger = get_logger("main")
    config = Config.from_file(Path("config.yaml"))
    migrator = BulkStagingMigrator(STAGING_COLLECTION_ID)
    
    print("="*60)
    print("🚀 ITGlue to SuperOps Bulk Migration")
    print("="*60)
    print(f"Target: Staging Collection")
    print(f"Collection ID: {STAGING_COLLECTION_ID}")
    print(f"URL: https://wyretechnology.superops.ai/#/kb/collection/{STAGING_COLLECTION_ID}")
    print()
    
    # Find all documents
    print("📂 Scanning for documents...")
    documents_path = Path("export-2/documents")
    all_documents = sorted(list(documents_path.rglob("*.html")))
    
    # Filter out already processed
    new_documents = [d for d in all_documents if str(d) not in migrator.processed_docs]
    
    print(f"📊 Found {len(all_documents)} total documents")
    print(f"✅ Already processed: {len(migrator.processed_docs)}")
    print(f"📝 To process: {len(new_documents)}")
    
    if not new_documents:
        print("\n✨ All documents have been processed!")
        return
    
    # Confirm before proceeding
    print("\n" + "="*60)
    print("⚠️  READY TO MIGRATE")
    print("="*60)
    print(f"This will migrate {len(new_documents)} documents to your staging collection.")
    print("Documents will include migration metadata for later organization.")
    print("\nPress Ctrl+C to cancel, or wait 5 seconds to continue...")
    
    try:
        await asyncio.sleep(5)
    except KeyboardInterrupt:
        print("\n❌ Migration cancelled")
        return
    
    # Initialize API client and migrate
    async with SuperOpsGraphQLClient(config.superops) as api_client:
        # Test connection
        print("\n🔌 Testing API connection...")
        if not await api_client.test_connection():
            print("❌ Failed to connect to SuperOps API")
            return
        print("✅ API connection successful")
        
        # Start migration
        start_time = datetime.now()
        
        try:
            await migrator.migrate_batch(
                new_documents,
                api_client,
                batch_size=10  # Process 10 at a time
            )
        except KeyboardInterrupt:
            print("\n\n⚠️  Migration interrupted by user")
        except Exception as e:
            print(f"\n\n❌ Migration error: {e}")
        finally:
            # Save final progress
            migrator.save_progress()
        
        # Calculate duration
        duration = datetime.now() - start_time
        minutes = duration.total_seconds() / 60
        
        # Final report
        print("\n" + "="*60)
        print("📊 MIGRATION REPORT")
        print("="*60)
        print(f"Duration: {minutes:.1f} minutes")
        print(f"Total Documents: {migrator.stats['total']}")
        print(f"✅ Successfully Migrated: {migrator.stats['success']}")
        print(f"⏭️  Skipped (existing): {migrator.stats['skipped']}")
        print(f"❌ Failed: {migrator.stats['failed']}")
        
        if migrator.stats['success'] > 0:
            rate = migrator.stats['success'] / (duration.total_seconds() / 60)
            print(f"📈 Migration Rate: {rate:.1f} docs/minute")
        
        if migrator.stats['failed'] > 0:
            print(f"\n⚠️  {migrator.stats['failed']} documents failed to migrate")
            print("Check migration_progress.json for error details")
        
        # Save final report
        report_file = f"migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w") as f:
            json.dump({
                "summary": migrator.stats,
                "duration_minutes": minutes,
                "staging_collection_id": STAGING_COLLECTION_ID,
                "timestamp": datetime.now().isoformat()
            }, f, indent=2)
        print(f"\n📄 Report saved to: {report_file}")
        
        print("\n" + "="*60)
        print("✨ MIGRATION COMPLETE!")
        print("="*60)
        print(f"\n📌 Next Steps:")
        print(f"1. Review documents at: https://wyretechnology.superops.ai/#/kb/collection/{STAGING_COLLECTION_ID}")
        print(f"2. Organize documents into appropriate collections")
        print(f"3. Update any broken links or references")
        print(f"4. Remove migration headers once organized")
        
        if migrator.stats['success'] > 0:
            print(f"\n🎉 Successfully migrated {migrator.stats['success']} documents to staging!")

if __name__ == "__main__":
    asyncio.run(main())