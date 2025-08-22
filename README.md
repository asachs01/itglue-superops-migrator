# ITGlue to SuperOps Migration Tool

Enterprise-grade Python tool for migrating ITGlue document exports to SuperOps Knowledge Base with zero human intervention during execution.

## Features

- 🚀 **Autonomous Operation**: Fire-and-forget migration with comprehensive error handling
- 📄 **Complete Document Support**: Handles procedural guides, templates, information storage, and step-by-step guides
- 🔄 **Resume Capability**: Interrupt and resume migrations without data loss
- 📎 **Attachment Handling**: Processes embedded images, base64 content, and file attachments
- ⚡ **Rate Limiting**: Respects SuperOps API limits (800 req/min) with intelligent throttling
- 📊 **Progress Tracking**: Real-time progress updates with ETA calculations
- 🔍 **Comprehensive Logging**: Structured logging to console, files, and system logs
- 🛡️ **Error Recovery**: Automatic retry with exponential backoff for transient failures
- 📈 **Detailed Reporting**: Migration statistics and audit trails

## Project Status

✅ **Production Ready** - Successfully migrated 638+ documents in production environment.

This tool has been tested and proven in production, successfully migrating large document collections from ITGlue to SuperOps.ai. The migration process handles complex HTML documents, preserves formatting, and maintains document relationships.

## Architecture

```
ITGlue Exports → Parser → Transformer → SuperOps API
      ↓            ↓           ↓            ↓
   CSV/HTML    Validation  Optimization  GraphQL/REST
      ↓            ↓           ↓            ↓
   Database ← Progress ← Error Handler ← Rate Limiter
```

## Installation

### Prerequisites

- Python 3.10 or higher
- ITGlue document exports (HTML format)
- SuperOps API credentials

### Install with Poetry (Recommended)

```bash
# Clone the repository
git clone https://github.com/asachs01/itglue-superops-migrator.git
cd itglue-superops-migrator

# Install Poetry if not already installed
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Install with pip

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package
pip install -e .
```

## Quick Start

### 1. Initialize Configuration

```bash
itglue-migrate init
```

This creates a `config.yaml` file. You'll be prompted for:
- SuperOps API Token
- SuperOps Subdomain
- Data Center (US/EU)

### 2. Edit Configuration

```yaml
# config.yaml
source:
  documents_path: export-2/documents
  csv_path: export-2/documents.csv
  attachments_path: export-2/attachments

superops:
  api_token: YOUR_API_TOKEN
  subdomain: your-subdomain
  data_center: us
  rate_limit: 750  # Safe under 800 limit

migration:
  batch_size: 10
  skip_existing: true
  dry_run: false  # Set to true for testing
```

### 3. Validate Configuration

```bash
itglue-migrate validate
```

This verifies:
- All paths exist
- API credentials are valid
- Connection to SuperOps is successful

### 4. Run Migration

```bash
# Full migration
itglue-migrate migrate

# Dry run (no API calls)
itglue-migrate migrate --dry-run

# Resume interrupted migration
itglue-migrate migrate --resume

# Limit number of documents
itglue-migrate migrate --limit 10

# Filter documents by pattern
itglue-migrate migrate --filter "onboarding|setup"
```

### 5. Generate Report

```bash
# Summary report
itglue-migrate report

# Detailed report
itglue-migrate report --format detailed

# Save to file
itglue-migrate report --output migration-report.txt
```

## Configuration Options

### Environment Variables

You can override configuration using environment variables:

```bash
export SUPEROPS_API_TOKEN=your_token
export SUPEROPS_SUBDOMAIN=your-subdomain
export MIGRATION_DRY_RUN=true
```

### Using .env File

Create a `.env` file in the project root:

```env
SUPEROPS_API_TOKEN=your_token_here
SUPEROPS_SUBDOMAIN=your-subdomain
SUPEROPS_DATA_CENTER=us
MIGRATION_BATCH_SIZE=20
LOGGING_LEVEL=DEBUG
```

## Customer Organization & Staging

### Understanding ITGlue Structure

ITGlue exports maintain customer segmentation in the document paths:
```
export-2/documents/
├── [Customer1 Name]/
│   ├── Processes/
│   ├── Documentation/
│   └── Templates/
├── [Customer2 Name]/
│   ├── Processes/
│   └── Documentation/
└── General/
    └── Standard Operating Procedures/
```

### Staging Collection Approach

The migration tool uses a **staging collection** in SuperOps where all documents are initially imported. This allows for:

1. **Safe Import** - All documents go to one collection first
2. **Review** - Check formatting and content preservation
3. **Organization** - Move documents to final locations at your pace
4. **Metadata Preservation** - Original paths stored in each document

```bash
# Migrate all documents to staging collection
itglue-migrate migrate --use-staging

# The tool will:
# 1. Create "Migration Staging Queue" collection
# 2. Import all documents with source metadata
# 3. Add migration info header to each document

# Review staging collection
itglue-migrate staging --status

# Export organization report
itglue-migrate staging --export-mapping mapping.csv
```

Each document in staging includes:
- Original ITGlue path/location
- Customer/folder information
- Migration timestamp
- Suggested final location

### Customer Mapping Configuration

Configure customer mapping in `config.yaml`:

```yaml
customer_mapping:
  # Map ITGlue customer names to SuperOps
  "ACME Corporation": "ACME Corp"
  "Contoso Ltd.": "Contoso"
  
  # Special handling for internal docs
  "WYRE Technology": "Internal Documentation"
  
  # Default collection for unmapped customers
  default_collection: "General Knowledge Base"
  
  # Create customer-specific collections
  create_customer_collections: true
  
  # Nest under parent collection
  parent_collection: "Client Documentation"
```

### Migration by Customer

```bash
# Migrate specific customer only
itglue-migrate migrate --customer "ACME Corp"

# Migrate multiple customers
itglue-migrate migrate --customers "ACME Corp,Contoso"

# Exclude specific customers
itglue-migrate migrate --exclude-customers "Test Client"

# List all customers found
itglue-migrate list-customers
```

## Advanced Usage

### Filtering Documents

```bash
# Migrate only specific organizations
itglue-migrate migrate --filter "WYRE Technology"

# Migrate by document type
itglue-migrate migrate --filter "onboarding|setup|install"

# Regex patterns supported
itglue-migrate migrate --filter "^DOC-826563[0-9]"
```

### Batch Processing

```bash
# Override batch size
itglue-migrate migrate --batch-size 5

# Process in smaller batches for debugging
itglue-migrate migrate --batch-size 1 --limit 5
```

### Logging Configuration

```yaml
logging:
  level: DEBUG  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  console: true
  file: logs/migration.log
  format: json  # json or text
  rotation_size: 10485760  # 10MB
  retention_days: 30
```

## Migration Process

### 1. Document Parsing
- Reads `documents.csv` for metadata
- Parses HTML files from `export-2/documents/`
- Detects document types (procedural, template, etc.)
- Extracts images, attachments, tables, and lists
- **Identifies customer/client from document path**

### 2. Staging & Organization
- **Creates staging area for documents by customer**
- **Maps ITGlue customer folders to SuperOps structure**
- **Allows manual review and reorganization before migration**
- **Supports customer-specific collections/categories**

### 3. Content Transformation
- Cleans and normalizes HTML
- Maps ITGlue categories to SuperOps
- Generates tags based on content
- Processes embedded images and attachments
- **Preserves customer context in metadata**

### 4. API Integration
- **Creates customer-specific collections if needed**
- Creates categories in SuperOps per customer
- Uploads attachments via REST API
- Creates KB articles via GraphQL
- Handles rate limiting automatically
- **Maintains customer segmentation in SuperOps**

### 5. Progress Tracking
- SQLite database tracks state
- Real-time progress bar with ETA
- Checkpoint saves every 60 seconds
- Resume from exact interruption point
- **Tracks migration by customer**

## Error Handling

The tool implements comprehensive error handling:

### Recoverable Errors
- Network timeouts → Exponential backoff retry
- Rate limits → Wait and retry
- API errors → Retry with backoff

### Non-Recoverable Errors
- File not found → Skip document
- Parse errors → Skip document
- Authentication failures → Stop migration

### Circuit Breaker
Prevents cascading failures by stopping after repeated errors of the same type.

## Database Schema

The tool uses SQLite to track migration state:

```sql
migration_runs     -- Overall migration tracking
documents         -- Document status and mapping
attachments       -- Attachment upload status
```

## Performance

Expected performance metrics:
- **Processing Rate**: 10-20 documents per minute
- **With Attachments**: 5-10 documents per minute
- **673 Documents**: ~2-4 hours total
- **Memory Usage**: < 500MB
- **Database Size**: ~10MB for 1000 documents

## Troubleshooting

### Common Issues

#### Authentication Error
```bash
Error: Invalid API token
```
**Solution**: Verify API token in SuperOps Settings → Your Profile → API Token

#### Rate Limit Exceeded
```bash
Error: 429 Too Many Requests
```
**Solution**: Reduce `rate_limit` in configuration (default: 750)

#### File Not Found
```bash
Error: Document file not found: DOC-8250506-17263224
```
**Solution**: Verify export paths in configuration

#### Memory Issues
For large migrations, increase Python memory:
```bash
export PYTHONMAXMEMORYMB=1024
itglue-migrate migrate
```

### Debug Mode

Enable debug logging:
```bash
# Via environment variable
export LOGGING__LEVEL=DEBUG

# Or in config.yaml
logging:
  level: DEBUG
```

### Check Database State

```bash
# View migration status
sqlite3 migration_state.db "SELECT * FROM migration_runs;"

# Check failed documents
sqlite3 migration_state.db "SELECT id, title, error_message FROM documents WHERE status='failed';"
```

## Project Structure

```
superops_import/
├── migrator/
│   ├── api/              # SuperOps API clients
│   ├── core/             # Database and orchestrator
│   ├── parsers/          # ITGlue parsers
│   ├── transformers/     # Content transformation
│   ├── utils/            # Error handling and progress
│   ├── config.py         # Configuration management
│   ├── logging.py        # Structured logging
│   └── cli.py            # Command-line interface
├── config.example.yaml   # Configuration template
├── pyproject.toml        # Project dependencies
└── README.md            # This file
```

## API Endpoints Used

### SuperOps GraphQL
- `getKbCategories` - List categories
- `createKbCategory` - Create category
- `createKbArticle` - Create article
- `getKbItems` - Check existing articles

### SuperOps REST
- `POST /upload` - Upload attachments

## Security Considerations

- API tokens are never logged
- Sensitive data is redacted in logs
- SSL verification enabled by default
- Credentials stored securely in environment

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

MIT License - See [LICENSE](LICENSE) file for details.

Copyright (c) 2025 WYRE Technology

## Support

For issues or questions:
- Create an issue in the repository
- Contact: databridge@wyre.technology

## Appendix

### Document Type Detection

The tool automatically detects document types:

| Type | Detection Method | SuperOps Category |
|------|-----------------|-------------------|
| Procedural | Contains "Prerequisites", "Procedures" | Procedures & SOPs |
| Template | Contains "[DELETEME]" markers | Templates |
| Step-by-Step | Contains Scribe step classes | How-To Guides |
| Information | Simple content structure | Reference Documentation |

### Category Mapping

ITGlue folders are mapped to SuperOps categories:

| ITGlue Folder | SuperOps Category |
|--------------|-------------------|
| Applications | Software & Applications |
| Contracts | Legal & Contracts |
| CrowdStrike | Security Tools |
| Documentation | General Documentation |
| Client folders | Client Documentation |

### Tag Generation

Tags are automatically generated from:
- Organization name
- Document type
- Technology keywords (Azure, AWS, Office365, etc.)
- Content characteristics (illustrated, technical, step-by-step)