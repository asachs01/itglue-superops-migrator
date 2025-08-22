"""CSV metadata parser for ITGlue document exports."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from pydantic import BaseModel, Field

from migrator.logging import get_logger


class DocumentMetadata(BaseModel):
    """Document metadata from CSV."""

    id: str
    organization: str
    name: str
    expires_on: Optional[datetime] = None
    owner: Optional[str] = None
    publisher: Optional[str] = None
    locator: str
    public: bool = False
    archived: bool = False
    help_center: bool = False
    related_documents: List[str] = Field(default_factory=list)
    file_path: Optional[Path] = None


class CSVMetadataParser:
    """Parser for ITGlue CSV metadata files."""

    # Expected CSV columns
    EXPECTED_COLUMNS = {
        "id",
        "organization",
        "name",
        "expires_on",
        "owner",
        "publisher",
        "locator",
        "public",
        "archived",
        "help_center",
    }

    def __init__(self, documents_path: Path) -> None:
        """Initialize the CSV parser.

        Args:
            documents_path: Path to documents directory for mapping files
        """
        self.documents_path = documents_path
        self.logger = get_logger("csv_parser")
        self._metadata_cache: Dict[str, DocumentMetadata] = {}
        self._organization_map: Dict[str, List[str]] = {}

    def parse_csv(self, csv_path: Path) -> Dict[str, DocumentMetadata]:
        """Parse the documents CSV file.

        Args:
            csv_path: Path to CSV file

        Returns:
            Dictionary mapping document ID to metadata

        Raises:
            ValueError: If CSV format is invalid
        """
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        self.logger.info("parsing_csv", path=str(csv_path))

        try:
            # Read CSV with pandas
            df = pd.read_csv(csv_path, encoding="utf-8", keep_default_na=False)
        except UnicodeDecodeError:
            # Try alternative encoding
            df = pd.read_csv(csv_path, encoding="latin-1", keep_default_na=False)

        # Validate columns
        self._validate_columns(df)

        # Parse each row
        metadata_dict = {}
        for _, row in df.iterrows():
            metadata = self._parse_row(row)
            if metadata:
                metadata_dict[metadata.locator] = metadata
                self._metadata_cache[metadata.locator] = metadata

                # Build organization map
                if metadata.organization not in self._organization_map:
                    self._organization_map[metadata.organization] = []
                self._organization_map[metadata.organization].append(metadata.locator)

        # Map file paths
        self._map_file_paths(metadata_dict)

        # Extract relationships
        self._extract_relationships(metadata_dict)

        self.logger.info(
            "csv_parsed",
            total_documents=len(metadata_dict),
            organizations=len(self._organization_map),
        )

        return metadata_dict

    def _validate_columns(self, df: pd.DataFrame) -> None:
        """Validate that required columns are present.

        Args:
            df: DataFrame to validate

        Raises:
            ValueError: If required columns are missing
        """
        columns = set(df.columns)
        missing = self.EXPECTED_COLUMNS - columns

        if missing:
            # Allow some flexibility for variations
            missing_critical = {"id", "organization", "name", "locator"} & missing
            if missing_critical:
                raise ValueError(f"Critical columns missing from CSV: {missing_critical}")

            self.logger.warning(
                "missing_columns",
                missing=list(missing),
                message="Some optional columns are missing",
            )

    def _parse_row(self, row: pd.Series) -> Optional[DocumentMetadata]:
        """Parse a single CSV row.

        Args:
            row: Pandas Series representing a row

        Returns:
            DocumentMetadata or None if row is invalid
        """
        try:
            # Parse expires_on date
            expires_on = None
            if row.get("expires_on"):
                try:
                    expires_on = pd.to_datetime(row["expires_on"])
                    if pd.isna(expires_on):
                        expires_on = None
                except Exception:
                    expires_on = None

            # Parse boolean fields
            def parse_bool(value: Any) -> bool:
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.lower() in ["yes", "true", "1"]
                return False

            metadata = DocumentMetadata(
                id=str(row.get("id", "")),
                organization=str(row.get("organization", "")),
                name=str(row.get("name", "")),
                expires_on=expires_on,
                owner=str(row.get("owner", "")) or None,
                publisher=str(row.get("publisher", "")) or None,
                locator=str(row.get("locator", "")),
                public=parse_bool(row.get("public", False)),
                archived=parse_bool(row.get("archived", False)),
                help_center=parse_bool(row.get("help_center", False)),
            )

            # Validate required fields
            if not metadata.locator or not metadata.name:
                self.logger.warning(
                    "invalid_row",
                    id=metadata.id,
                    reason="Missing required fields",
                )
                return None

            return metadata

        except Exception as e:
            self.logger.error(
                "row_parse_error",
                error=str(e),
                row_id=row.get("id"),
            )
            return None

    def _map_file_paths(self, metadata_dict: Dict[str, DocumentMetadata]) -> None:
        """Map document metadata to actual file paths.

        Args:
            metadata_dict: Dictionary of document metadata
        """
        # Scan documents directory for HTML files
        doc_files = {}
        for html_file in self.documents_path.rglob("*.html"):
            # Extract document ID from path
            parent_dir = html_file.parent.name
            if parent_dir.startswith("DOC-"):
                # Extract locator (DOC-XXXXX-XXXXXXX)
                match = re.match(r"(DOC-\d+-\d+)", parent_dir)
                if match:
                    locator = match.group(1)
                    doc_files[locator] = html_file

        # Map paths to metadata
        for locator, metadata in metadata_dict.items():
            if locator in doc_files:
                metadata.file_path = doc_files[locator]
            else:
                self.logger.warning(
                    "file_not_found",
                    locator=locator,
                    name=metadata.name,
                )

    def _extract_relationships(self, metadata_dict: Dict[str, DocumentMetadata]) -> None:
        """Extract document relationships.

        Args:
            metadata_dict: Dictionary of document metadata
        """
        # Look for relationships in document names
        for locator, metadata in metadata_dict.items():
            related = []

            # Check for references to other documents in the name
            for other_locator, other_metadata in metadata_dict.items():
                if locator == other_locator:
                    continue

                # Check if document name references another
                if other_metadata.name in metadata.name:
                    related.append(other_locator)
                # Check for common patterns (e.g., "Part 1", "Part 2")
                elif self._are_related(metadata.name, other_metadata.name):
                    related.append(other_locator)

            metadata.related_documents = related

    def _are_related(self, name1: str, name2: str) -> bool:
        """Check if two documents are related based on their names.

        Args:
            name1: First document name
            name2: Second document name

        Returns:
            True if documents appear related
        """
        # Remove common variations
        clean1 = re.sub(r"[-_\s]+", " ", name1.lower())
        clean2 = re.sub(r"[-_\s]+", " ", name2.lower())

        # Check for part numbers
        part_pattern = r"(.*?)\s*(?:part|section|chapter|step)\s*(\d+)"
        match1 = re.match(part_pattern, clean1)
        match2 = re.match(part_pattern, clean2)

        if match1 and match2:
            # Same base name, different part numbers
            if match1.group(1) == match2.group(1):
                return True

        # Check for version numbers
        version_pattern = r"(.*?)\s*v?(\d+(?:\.\d+)*)"
        match1 = re.match(version_pattern, clean1)
        match2 = re.match(version_pattern, clean2)

        if match1 and match2:
            # Same base name, different versions
            if match1.group(1) == match2.group(1):
                return True

        # Check for common prefixes (at least 10 characters)
        common_len = 0
        for c1, c2 in zip(clean1, clean2):
            if c1 == c2:
                common_len += 1
            else:
                break

        if common_len >= 10 and common_len > min(len(clean1), len(clean2)) * 0.5:
            return True

        return False

    def get_metadata_by_locator(self, locator: str) -> Optional[DocumentMetadata]:
        """Get metadata for a specific document.

        Args:
            locator: Document locator ID

        Returns:
            Document metadata or None
        """
        return self._metadata_cache.get(locator)

    def get_documents_by_organization(self, organization: str) -> List[DocumentMetadata]:
        """Get all documents for an organization.

        Args:
            organization: Organization name

        Returns:
            List of document metadata
        """
        locators = self._organization_map.get(organization, [])
        return [self._metadata_cache[loc] for loc in locators if loc in self._metadata_cache]

    def get_organizations(self) -> List[str]:
        """Get all unique organizations.

        Returns:
            List of organization names
        """
        return list(self._organization_map.keys())

    def build_dependency_graph(self) -> Dict[str, Set[str]]:
        """Build a dependency graph based on document relationships.

        Returns:
            Dictionary mapping document ID to set of dependent document IDs
        """
        graph = {}
        for locator, metadata in self._metadata_cache.items():
            graph[locator] = set(metadata.related_documents)
        return graph

    def get_migration_order(self) -> List[str]:
        """Get optimal migration order based on dependencies.

        Returns:
            Ordered list of document locators
        """
        # Build dependency graph
        graph = self.build_dependency_graph()

        # Topological sort
        visited = set()
        order = []

        def visit(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in graph.get(node, set()):
                visit(dep)
            order.append(node)

        # Visit all nodes
        for locator in self._metadata_cache:
            visit(locator)

        return order

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the parsed metadata.

        Returns:
            Statistics dictionary
        """
        total = len(self._metadata_cache)
        if total == 0:
            return {
                "total_documents": 0,
                "organizations": 0,
                "public_documents": 0,
                "archived_documents": 0,
                "help_center_documents": 0,
                "documents_with_files": 0,
                "documents_with_relationships": 0,
            }

        return {
            "total_documents": total,
            "organizations": len(self._organization_map),
            "public_documents": sum(1 for m in self._metadata_cache.values() if m.public),
            "archived_documents": sum(1 for m in self._metadata_cache.values() if m.archived),
            "help_center_documents": sum(
                1 for m in self._metadata_cache.values() if m.help_center
            ),
            "documents_with_files": sum(
                1 for m in self._metadata_cache.values() if m.file_path
            ),
            "documents_with_relationships": sum(
                1 for m in self._metadata_cache.values() if m.related_documents
            ),
            "average_relationships": (
                sum(len(m.related_documents) for m in self._metadata_cache.values()) / total
            ),
        }

    def validate_metadata(self) -> Dict[str, List[str]]:
        """Validate all parsed metadata.

        Returns:
            Dictionary mapping document locators to validation errors
        """
        errors = {}

        for locator, metadata in self._metadata_cache.items():
            doc_errors = []

            # Check for missing file
            if not metadata.file_path or not metadata.file_path.exists():
                doc_errors.append("HTML file not found")

            # Check for missing organization
            if not metadata.organization:
                doc_errors.append("Organization is missing")

            # Check for expired documents
            if metadata.expires_on and metadata.expires_on < datetime.now():
                doc_errors.append(f"Document expired on {metadata.expires_on}")

            # Check for broken relationships
            for related in metadata.related_documents:
                if related not in self._metadata_cache:
                    doc_errors.append(f"Related document not found: {related}")

            if doc_errors:
                errors[locator] = doc_errors

        return errors