#!/usr/bin/env python3
"""Create debug package for SuperOps team."""

import zipfile
from pathlib import Path

def create_debug_package():
    """Create a zip file with all debug information."""
    
    files_to_include = [
        "superops_migration_errors.md",
        "email_to_superops.md",
        "test_create_category.py",
        "test_create_article.py",
        "test_minimal_article.py", 
        "test_visibility_types.py",
        "test_full_visibility.py",
        "test_simple_visibility.py",
        "test_get_existing.py",
        "test_mutation_schema.py",
        "test_input_types.py",
        "test_nested_types.py",
        "test_visibility.py",
        "test_get_account.py",
        "test_kb_introspect.py"
    ]
    
    # Also include a sample working mutation and a failing one
    sample_content = """# Sample API Calls

## WORKING: Create Category/Collection
```graphql
mutation CreateKbCollection($input: CreateKbCollectionInput!) {
    createKbCollection(input: $input) {
        itemId
        name
    }
}
```

Variables:
```json
{
  "input": {
    "name": "Test Category"
  }
}
```

Response: SUCCESS - Returns itemId

## FAILING: Create Article
```graphql
mutation CreateKbArticle($input: CreateKbArticleInput!) {
    createKbArticle(input: $input) {
        itemId
        name
    }
}
```

Variables (all variations fail):
```json
{
  "input": {
    "name": "Test Article",
    "content": "<p>Test content</p>",
    "parent": {"itemId": "7986891993049776128"},
    "status": "PUBLISHED",
    "visibility": {
      "added": [{
        "portalType": "TECHNICIAN",
        "userSharedType": "AllUsers"
      }]
    },
    "loginRequired": false
  }
}
```

Response: ERROR - Internal Server Error(s) while executing query
"""
    
    # Write the sample content
    with open("sample_api_calls.md", "w") as f:
        f.write(sample_content)
    
    # Create the zip file
    with zipfile.ZipFile("superops_migration_debug.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add the sample
        zipf.write("sample_api_calls.md")
        
        # Add all test files
        for file in files_to_include:
            if Path(file).exists():
                zipf.write(file)
                print(f"Added: {file}")
            else:
                print(f"Skipped (not found): {file}")
        
        # Add a README
        readme_content = """# SuperOps Migration Debug Package

This package contains test scripts and documentation for debugging the ITGlue to SuperOps Knowledge Base migration issue.

## Contents

1. **superops_migration_errors.md** - Detailed technical error report
2. **email_to_superops.md** - Draft email explaining the issue
3. **sample_api_calls.md** - Working vs failing API examples
4. **test_*.py** - Various test scripts demonstrating the issue

## Quick Start

1. Install dependencies: `pip install httpx python-dotenv`
2. Create .env file with:
   ```
   SUPEROPS_API_TOKEN=your_token_here
   SUPEROPS__SUBDOMAIN=your_subdomain
   ```
3. Run any test script: `python3 test_create_category.py`

## Key Issue

The createKbArticle mutation fails with "Internal Server Error" when trying to create articles, 
specifically related to the visibility field configuration. Categories create successfully.

## Contact

Created for SuperOps support team to debug Knowledge Base article creation via GraphQL API.
"""
        zipf.writestr("README.md", readme_content)
    
    print(f"\nCreated: superops_migration_debug.zip")
    print(f"Size: {Path('superops_migration_debug.zip').stat().st_size / 1024:.1f} KB")

if __name__ == "__main__":
    create_debug_package()