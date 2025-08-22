#!/bin/bash

# ITGlue to SuperOps Migration - Docker Helper Script
# Usage: ./docker-migrate.sh [command] [options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env file exists
check_env() {
    if [ ! -f .env ]; then
        echo -e "${YELLOW}Warning: .env file not found!${NC}"
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo -e "${RED}Please edit .env file with your configuration before running migration.${NC}"
        exit 1
    fi
}

# Build Docker image
build() {
    echo -e "${GREEN}Building Docker image...${NC}"
    docker-compose build
}

# Run migration
migrate() {
    check_env
    echo -e "${GREEN}Starting migration...${NC}"
    docker-compose run --rm migrator python -m migrator.cli migrate "$@"
}

# Run dry-run migration
dry_run() {
    check_env
    echo -e "${YELLOW}Running migration in dry-run mode...${NC}"
    docker-compose run --rm migrator python -m migrator.cli migrate --dry-run "$@"
}

# Migrate to staging collection
staging() {
    check_env
    if [ -z "$STAGING_COLLECTION_ID" ]; then
        echo -e "${RED}Error: STAGING_COLLECTION_ID not set in .env file${NC}"
        exit 1
    fi
    echo -e "${GREEN}Migrating to staging collection...${NC}"
    docker-compose run --rm migrator python migrate_all_to_staging.py
}

# Validate configuration
validate() {
    check_env
    echo -e "${GREEN}Validating configuration...${NC}"
    docker-compose run --rm migrator python -m migrator.cli validate
}

# Show migration report
report() {
    check_env
    echo -e "${GREEN}Generating migration report...${NC}"
    docker-compose run --rm migrator python -m migrator.cli report "$@"
}

# Interactive shell
shell() {
    check_env
    echo -e "${GREEN}Starting interactive shell...${NC}"
    docker-compose run --rm migrator /bin/bash
}

# View logs
logs() {
    docker-compose logs -f migrator
}

# Clean up
clean() {
    echo -e "${YELLOW}Cleaning up Docker resources...${NC}"
    docker-compose down -v
    echo -e "${GREEN}Cleanup complete!${NC}"
}

# Show help
show_help() {
    cat << EOF
ITGlue to SuperOps Migration - Docker Helper

Usage: ./docker-migrate.sh [command] [options]

Commands:
    build       Build Docker image
    migrate     Run full migration
    dry-run     Run migration in dry-run mode
    staging     Migrate all documents to staging collection
    validate    Validate configuration
    report      Generate migration report
    shell       Start interactive shell
    logs        View migration logs
    clean       Clean up Docker resources
    help        Show this help message

Examples:
    ./docker-migrate.sh build
    ./docker-migrate.sh dry-run --limit 10
    ./docker-migrate.sh migrate
    ./docker-migrate.sh staging
    ./docker-migrate.sh report --format detailed

Environment:
    Edit .env file to configure:
    - SUPEROPS_API_TOKEN
    - SUPEROPS_SUBDOMAIN
    - EXPORT_PATH (path to ITGlue export)
    - STAGING_COLLECTION_ID (optional)

EOF
}

# Main script logic
case "$1" in
    build)
        build
        ;;
    migrate)
        shift
        migrate "$@"
        ;;
    dry-run|dryrun)
        shift
        dry_run "$@"
        ;;
    staging)
        staging
        ;;
    validate)
        validate
        ;;
    report)
        shift
        report "$@"
        ;;
    shell)
        shell
        ;;
    logs)
        logs
        ;;
    clean)
        clean
        ;;
    help|--help|-h|"")
        show_help
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help
        exit 1
        ;;
esac