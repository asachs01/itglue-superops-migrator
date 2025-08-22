# ITGlue to SuperOps Migration Tool - Setup Guide

## ✅ What's Been Completed

All 11 core tasks have been implemented:

1. **Project Setup** - Python project with Poetry configuration
2. **Database** - SQLite state tracking with full schema
3. **ITGlue Parser** - HTML document parsing with type detection
4. **CSV Parser** - Metadata extraction from documents.csv
5. **GraphQL Client** - SuperOps KB API integration
6. **REST Client** - Attachment upload handling
7. **Content Transformer** - ITGlue to SuperOps format conversion
8. **Migration Orchestrator** - Complete migration workflow
9. **Error Handling** - Retry logic, circuit breakers, recovery
10. **Progress Tracking** - Real-time progress with ETA
11. **Testing & Documentation** - Test scripts and comprehensive docs

## 🚀 Quick Start - What You Need to Do

### Step 1: Complete Environment Setup

You need to add your SuperOps subdomain to the `.env` file:

```bash
# Edit .env file and add:
SUPEROPS__SUBDOMAIN=your_subdomain_here

# For example, if your SuperOps URL is: acme.superops.com
# Add: SUPEROPS__SUBDOMAIN=acme
```

Your API token is already in the `.env` file as `SUPEROPS_API_TOKEN`.

### Step 2: Install Dependencies (if not already done)

```bash
# Using the virtual environment we created:
source venv/bin/activate
pip install -r requirements.txt

# Or if you prefer Poetry:
poetry install
```

### Step 3: Run Test Migration (10 Documents)

```bash
# Activate virtual environment
source venv/bin/activate

# Run test migration
python test_migration.py
```

This will:
- Validate your configuration
- Test API connectivity
- Migrate 10 documents as a test
- Show you the results

### Step 4: Check Results in SuperOps

1. Log into your SuperOps account
2. Navigate to Knowledge Base
3. Look for the newly created articles
4. Verify content formatting and attachments

### Step 5: Run Full Migration (if test is successful)

```bash
# For full migration of all 673 documents:
python -m migrator.cli migrate

# Or with specific options:
python -m migrator.cli migrate --batch-size 20
python -m migrator.cli migrate --limit 100  # Limit to 100 docs
python -m migrator.cli migrate --resume      # Resume interrupted migration
```

## 📁 Project Structure

```
superops_import/
├── migrator/               # Main application code
│   ├── api/               # SuperOps API clients
│   ├── core/              # Database and orchestrator
│   ├── parsers/           # ITGlue document parsers
│   ├── transformers/      # Content transformation
│   ├── utils/             # Error handling and progress
│   ├── config.py          # Configuration management
│   ├── logging.py         # Structured logging
│   └── cli.py             # Command-line interface
├── export-2/              # Your ITGlue export data
│   ├── documents/         # HTML documents (673 files)
│   ├── documents.csv      # Document metadata
│   └── attachments/       # File attachments
├── venv/                  # Python virtual environment
├── config.yaml            # Configuration file
├── .env                   # Environment variables (API token)
├── test_migration.py      # Test script for 10 documents
├── test_installation.py   # Installation verification
└── README.md              # Full documentation

```

## 🔧 Configuration Files

### `.env` (Environment Variables)
```env
SUPEROPS_API_TOKEN=your_token_here        # ✅ Already set
SUPEROPS__SUBDOMAIN=your_subdomain        # ⚠️ YOU NEED TO ADD THIS
SUPEROPS__DATA_CENTER=us                  # Optional (default: us)
```

### `config.yaml` (Main Configuration)
- Already configured with sensible defaults
- Can be overridden with environment variables
- Includes paths, rate limits, batch sizes, etc.

## 📊 Expected Performance

- **Processing Rate**: 10-20 documents per minute
- **With Attachments**: 5-10 documents per minute
- **Total Time for 673 docs**: ~2-4 hours
- **Memory Usage**: < 500MB

## 🛡️ Safety Features

1. **Dry Run Mode** - Test without making API calls
2. **Resume Capability** - Continue interrupted migrations
3. **Rate Limiting** - Respects SuperOps API limits (800 req/min)
4. **Error Recovery** - Automatic retry with exponential backoff
5. **Progress Tracking** - Real-time status with checkpoints
6. **State Management** - SQLite database tracks all operations

## 📝 Available Commands

```bash
# Initialize configuration
python -m migrator.cli init

# Validate configuration
python -m migrator.cli validate

# Run migration
python -m migrator.cli migrate [OPTIONS]
  --dry-run           # Test without API calls
  --resume            # Resume from checkpoint
  --limit N           # Limit to N documents
  --batch-size N      # Override batch size
  --filter "pattern"  # Filter by regex pattern

# Generate report
python -m migrator.cli report
  --format detailed   # Detailed report
  --output file.txt   # Save to file

# Clean up state
python -m migrator.cli clean
```

## ⚠️ Important Notes

1. **API Token Security**: Your API token is stored in `.env` which is gitignored
2. **Subdomain Required**: You must set SUPEROPS__SUBDOMAIN in .env
3. **Data Validation**: The tool validates all paths before starting
4. **Incremental Migration**: Can resume from exact interruption point
5. **Logging**: Check `logs/migration.log` for detailed information

## 🐛 Troubleshooting

### "SUPEROPS__SUBDOMAIN not set"
Add your subdomain to the `.env` file:
```bash
echo "SUPEROPS__SUBDOMAIN=your_subdomain" >> .env
```

### "API connection failed"
- Verify your API token is correct
- Check subdomain matches your SuperOps instance
- Confirm data center (us/eu) is correct

### "Document file not found"
- Ensure `export-2/` directory contains ITGlue exports
- Check file paths in `documents.csv` match actual files

### Rate Limit Errors
- Reduce `rate_limit` in `config.yaml` (default: 750)
- Tool automatically handles rate limits with backoff

## 📞 Next Steps After Setup

1. **Run Test Migration** - Start with 10 documents
2. **Verify in SuperOps** - Check migrated content
3. **Review Logs** - Check for any warnings
4. **Run Full Migration** - Process all 673 documents
5. **Generate Report** - Get migration statistics

## 🎯 Ready to Start?

1. Add your subdomain to `.env`:
   ```bash
   SUPEROPS__SUBDOMAIN=your_subdomain_here
   ```

2. Run the test:
   ```bash
   source venv/bin/activate
   python test_migration.py
   ```

That's it! The tool will handle everything else automatically.