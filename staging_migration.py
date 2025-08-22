#!/usr/bin/env python3
"""Migration script with staging collection approach for SuperOps KB."""

import asyncio
import os
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv

from migrator.config import Config
from migrator.parsers.html_parser import ITGlueDocumentParser
from migrator.transformers.content_transformer import ContentTransformer
from migrator.api.graphql_client import SuperOpsGraphQLClient
from migrator.logging import get_logger

# Load environment
load_dotenv()

class StagingMigrator:
    """Handles migration with initial staging collection approach."""
    
    STAGING_COLLECTION_NAME = "Migration Staging Queue"
    STAGING_COLLECTION_DESC = "Temporary staging area for ITGlue document imports. Documents here are pending organization into their final locations."
    
    def __init__(self, config: Config):
        """Initialize the staging migrator."""
        self.config = config
        self.logger = get_logger("staging_migrator")
        self.parser = ITGlueDocumentParser()
        self.attachments_path = Path("export-2/attachments")
        self.transformer = ContentTransformer(attachments_base_path=self.attachments_path)
        self.staging_collection_id = None
        
    async def ensure_staging_collection(self, api_client: SuperOpsGraphQLClient) -> str:
        """Ensure the staging collection exists and return its ID."""
        
        self.logger.info("Checking for staging collection...")
        
        # Get existing collections
        categories_response = await api_client.get_kb_categories()
        categories = categories_response.get("categories", [])
        
        # Check if staging collection exists
        for category in categories:
            if category.get("name") == self.STAGING_COLLECTION_NAME:
                self.staging_collection_id = category.get("itemId")
                self.logger.info(f"Found existing staging collection: {self.staging_collection_id}")
                return self.staging_collection_id
        
        # Create staging collection if it doesn't exist
        self.logger.info("Creating staging collection...")
        collection = await api_client.create_kb_category(
            name=self.STAGING_COLLECTION_NAME,
            description=self.STAGING_COLLECTION_DESC
        )
        
        self.staging_collection_id = collection.get("itemId")
        self.logger.info(f"Created staging collection: {self.staging_collection_id}")
        
        return self.staging_collection_id
    
    async def migrate_to_staging(
        self, 
        document_path: Path,
        dry_run: bool = False,
        preserve_path_info: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Migrate a single document to the staging collection."""
        
        if not document_path.exists():
            self.logger.error(f"Document not found: {document_path}")
            return None
        
        # Parse document
        self.logger.info(f"Parsing: {document_path.name}")
        try:
            parsed = self.parser.parse_file(document_path)
        except Exception as e:
            self.logger.error(f"Failed to parse {document_path}: {e}")
            return None
        
        # Transform content
        self.logger.info("Transforming content...")
        try:
            transformed = self.transformer.transform(parsed)
        except Exception as e:
            self.logger.error(f"Failed to transform: {e}")
            return None
        
        # Add source path information to help with later organization
        if preserve_path_info:
            # Extract customer/category info from path
            rel_path = document_path.relative_to(Path("export-2/documents"))
            path_parts = rel_path.parts[:-1]  # Exclude the filename
            
            source_info = {
                "itglue_path": str(rel_path),
                "customer_folder": path_parts[0] if path_parts else "Unknown",
                "category_folder": path_parts[1] if len(path_parts) > 1 else "Root",
                "original_location": "/".join(path_parts)
            }
            
            # Add to metadata
            if transformed.metadata:
                transformed.metadata["source_organization"] = source_info
            else:
                transformed.metadata = {"source_organization": source_info}
            
            # Prepend source info to content for visibility
            source_note = f"""
<div style="background-color: #f0f0f0; padding: 10px; margin-bottom: 20px; border: 1px solid #ddd;">
<strong>📁 Migration Information:</strong><br/>
<em>Original Location:</em> {source_info['original_location']}<br/>
<em>Customer/Folder:</em> {source_info['customer_folder']}<br/>
<em>Category:</em> {source_info['category_folder']}<br/>
<em>Status:</em> Pending final organization
</div>
"""
            transformed.content_html = source_note + transformed.content_html
        
        if dry_run:
            self.logger.info(f"[DRY RUN] Would create article: {transformed.title}")
            return {
                "title": transformed.title,
                "dry_run": True,
                "source_info": source_info if preserve_path_info else None
            }
        
        return {
            "title": transformed.title,
            "content": transformed.content_html,
            "metadata": transformed.metadata,
            "source_info": source_info if preserve_path_info else None
        }

async def main():
    """Main migration function with staging approach."""
    
    # Setup
    logger = get_logger("main")
    config = Config.from_file(Path("config.yaml"))
    migrator = StagingMigrator(config)
    
    print("="*60)
    print("ITGlue to SuperOps Migration - Staging Approach")
    print("="*60)
    print("\nThis will migrate all documents to a staging collection")
    print("where they can be reviewed and organized before final placement.")
    print()
    
    # Initialize API client
    async with SuperOpsGraphQLClient(config.superops) as api_client:
        # Test connection
        print("1. Testing API connection...")
        if not await api_client.test_connection():
            print("❌ Failed to connect to SuperOps API")
            return
        print("✅ API connection successful")
        
        # Create/verify staging collection
        print("\n2. Setting up staging collection...")
        staging_id = await migrator.ensure_staging_collection(api_client)
        print(f"✅ Staging collection ready: {migrator.STAGING_COLLECTION_NAME}")
        print(f"   ID: {staging_id}")
        
        # Find documents to migrate
        print("\n3. Scanning for documents...")
        documents_path = Path("export-2/documents")
        all_documents = list(documents_path.rglob("*.html"))
        print(f"   Found {len(all_documents)} documents")
        
        # Filter to a few test documents
        test_docs = all_documents[:5]  # Start with just 5 for testing
        
        print(f"\n4. Migrating {len(test_docs)} documents to staging...")
        print("-"*50)
        
        success_count = 0
        error_count = 0
        
        for i, doc_path in enumerate(test_docs, 1):
            print(f"\n[{i}/{len(test_docs)}] Processing: {doc_path.name}")
            
            # Prepare document
            doc_data = await migrator.migrate_to_staging(doc_path, dry_run=False)
            
            if not doc_data:
                error_count += 1
                continue
            
            # Check if already exists
            existing_id = await api_client.check_article_exists(doc_data["title"])
            if existing_id:
                print(f"   ⚠️  Already exists, skipping")
                continue
            
            # Create in staging collection
            try:
                article = await api_client.create_kb_article(
                    title=doc_data["title"],
                    content=doc_data["content"],
                    category_id=staging_id,  # Use staging collection
                    metadata=doc_data["metadata"]
                )
                
                if article and article.get("itemId"):
                    success_count += 1
                    print(f"   ✅ Created in staging: {article['itemId']}")
                    
                    # Display source info for reference
                    if doc_data.get("source_info"):
                        info = doc_data["source_info"]
                        print(f"      Original: {info['original_location']}")
                else:
                    error_count += 1
                    print(f"   ❌ Failed to create article")
                    
            except Exception as e:
                error_count += 1
                print(f"   ❌ Error: {e}")
        
        # Summary
        print("\n" + "="*60)
        print("MIGRATION TO STAGING COMPLETE")
        print("="*60)
        print(f"✅ Successfully staged: {success_count} documents")
        if error_count > 0:
            print(f"❌ Errors: {error_count} documents")
        
        print("\n📋 Next Steps:")
        print("1. Review documents in the staging collection in SuperOps")
        print("2. Create appropriate customer/category collections")
        print("3. Move documents from staging to their final locations")
        print("4. Use the source information in each document to guide organization")
        
        print("\n💡 Tips:")
        print("• Documents include migration metadata at the top")
        print("• Original folder structure is preserved in the metadata")
        print("• You can bulk-select and move documents in SuperOps UI")
        print("• Consider creating a mapping file for automated organization")

if __name__ == "__main__":
    asyncio.run(main())