"""ITGlue HTML document parser."""

import hashlib
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, NavigableString, Tag
from pydantic import BaseModel, Field

from migrator.logging import get_logger


class DocumentType(str, Enum):
    """ITGlue document types."""

    PROCEDURAL = "procedural"
    TEMPLATE = "template"
    INFORMATION = "information"
    STEP_BY_STEP = "step_by_step"
    UNKNOWN = "unknown"


class ParsedImage(BaseModel):
    """Parsed image from HTML."""

    src: str
    alt: Optional[str] = None
    title: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_base64: bool = False
    base64_data: Optional[str] = None
    mime_type: Optional[str] = None


class ParsedAttachment(BaseModel):
    """Parsed attachment reference."""

    href: str
    text: str
    filename: Optional[str] = None
    is_external: bool = False


class ParsedDocument(BaseModel):
    """Parsed ITGlue document."""

    document_id: str
    title: str
    organization: Optional[str] = None
    document_type: DocumentType = DocumentType.UNKNOWN
    content_html: str
    content_text: str
    headings: List[Dict[str, str]] = Field(default_factory=list)
    images: List[ParsedImage] = Field(default_factory=list)
    attachments: List[ParsedAttachment] = Field(default_factory=list)
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    lists: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""


class ITGlueDocumentParser:
    """Parser for ITGlue HTML document exports."""

    # Document type detection patterns
    PROCEDURAL_MARKERS = [
        "processname",
        "prerequisites",
        "procedures",
        "references",
        "Pre-Requisites",
        "Procedure",
    ]
    TEMPLATE_MARKERS = ["[DELETEME]", "[TEMPLATE", "[COPY ME]"]
    STEP_BY_STEP_MARKERS = ["scribe-step", "scribe-screenshot"]

    def __init__(self) -> None:
        """Initialize the parser."""
        self.logger = get_logger("html_parser")

    def parse_document(self, file_path: Path) -> ParsedDocument:
        """Parse an ITGlue HTML document.

        Args:
            file_path: Path to HTML file

        Returns:
            Parsed document

        Raises:
            ValueError: If document cannot be parsed
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        # Extract document ID from path
        document_id = self._extract_document_id(file_path)

        # Read and parse HTML
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except UnicodeDecodeError:
            # Try alternative encodings
            with open(file_path, "r", encoding="latin-1") as f:
                html_content = f.read()

        soup = BeautifulSoup(html_content, "lxml")

        # Detect document type
        document_type = self._detect_document_type(soup)

        # Extract title
        title = self._extract_title(soup, file_path)

        # Extract organization (if available)
        organization = self._extract_organization(file_path)

        # Parse content based on type
        content_html, content_text = self._extract_content(soup)

        # Extract structured elements
        headings = self._extract_headings(soup)
        images = self._extract_images(soup)
        attachments = self._extract_attachments(soup)
        tables = self._extract_tables(soup)
        lists = self._extract_lists(soup)

        # Extract metadata
        metadata = self._extract_metadata(soup, document_type)

        # Calculate content hash
        content_hash = hashlib.sha256(content_html.encode()).hexdigest()

        document = ParsedDocument(
            document_id=document_id,
            title=title,
            organization=organization,
            document_type=document_type,
            content_html=content_html,
            content_text=content_text,
            headings=headings,
            images=images,
            attachments=attachments,
            tables=tables,
            lists=lists,
            metadata=metadata,
            content_hash=content_hash,
        )

        self.logger.debug(
            "document_parsed",
            document_id=document_id,
            title=title,
            type=document_type.value,
            images=len(images),
            attachments=len(attachments),
        )

        return document

    def _extract_document_id(self, file_path: Path) -> str:
        """Extract document ID from file path.

        Args:
            file_path: Path to document

        Returns:
            Document ID
        """
        # Pattern: DOC-8250506-17263224
        parent_dir = file_path.parent.name
        match = re.match(r"(DOC-\d+-\d+)", parent_dir)
        if match:
            return match.group(1)

        # Fallback to parent directory name
        return parent_dir

    def _extract_title(self, soup: BeautifulSoup, file_path: Path) -> str:
        """Extract document title.

        Args:
            soup: BeautifulSoup object
            file_path: Path to document

        Returns:
            Document title
        """
        # Try to find title in H1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        # Try to find title in processname
        process_name = soup.find(id="processname")
        if process_name:
            text = process_name.get_text(strip=True)
            if text.startswith("Process Name:"):
                return text.replace("Process Name:", "").strip()

        # Try to extract from parent directory name
        parent_dir = file_path.parent.name
        # Pattern: DOC-8250506-17263224 Title Here
        match = re.match(r"DOC-\d+-\d+\s+(.+)", parent_dir)
        if match:
            return match.group(1)

        # Fallback to file name without extension
        return file_path.stem

    def _extract_organization(self, file_path: Path) -> Optional[str]:
        """Extract organization from file path.

        Args:
            file_path: Path to document

        Returns:
            Organization name or None
        """
        # Try to extract from parent directories
        # Pattern: documents/Organization/DOC-xxx/
        parts = file_path.parts
        if "documents" in parts:
            doc_idx = parts.index("documents")
            if doc_idx + 1 < len(parts):
                org_candidate = parts[doc_idx + 1]
                # Check if it's not a DOC- pattern
                if not org_candidate.startswith("DOC-"):
                    return org_candidate

        return None

    def _detect_document_type(self, soup: BeautifulSoup) -> DocumentType:
        """Detect the type of ITGlue document.

        Args:
            soup: BeautifulSoup object

        Returns:
            Document type
        """
        html_text = str(soup).lower()

        # Check for step-by-step guides (Scribe)
        if any(marker in html_text for marker in self.STEP_BY_STEP_MARKERS):
            return DocumentType.STEP_BY_STEP

        # Check for templates
        if any(marker in str(soup) for marker in self.TEMPLATE_MARKERS):
            return DocumentType.TEMPLATE

        # Check for procedural documents
        if any(marker.lower() in html_text for marker in self.PROCEDURAL_MARKERS):
            return DocumentType.PROCEDURAL

        # Check for simple information storage
        content_div = soup.find("div", class_="text-section")
        if content_div:
            # Count structural elements
            headings = content_div.find_all(["h1", "h2", "h3", "h4"])
            tables = content_div.find_all("table")
            lists = content_div.find_all(["ol", "ul"])

            if len(headings) <= 1 and len(tables) == 0 and len(lists) <= 1:
                return DocumentType.INFORMATION

        return DocumentType.UNKNOWN

    def _extract_content(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """Extract main content from document.

        Args:
            soup: BeautifulSoup object

        Returns:
            Tuple of (HTML content, text content)
        """
        # Find main content div
        content_div = soup.find("div", class_="text-section")
        if not content_div:
            content_div = soup.find("body")
            if not content_div:
                return "", ""

        # Clean HTML content
        html_content = self._clean_html(str(content_div))

        # Extract text content
        text_content = content_div.get_text(separator="\n", strip=True)

        return html_content, text_content

    def _clean_html(self, html: str) -> str:
        """Clean HTML content.

        Args:
            html: Raw HTML string

        Returns:
            Cleaned HTML
        """
        # Remove script and style tags
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()

        # Remove empty paragraphs
        for p in soup.find_all("p"):
            if not p.get_text(strip=True):
                p.decompose()

        return str(soup)

    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract all headings from document.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of headings with level and text
        """
        headings = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            headings.append({
                "level": tag.name,
                "text": tag.get_text(strip=True),
                "id": tag.get("id", ""),
            })
        return headings

    def _extract_images(self, soup: BeautifulSoup) -> List[ParsedImage]:
        """Extract all images from document.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of parsed images
        """
        images = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src:
                continue

            image = ParsedImage(
                src=src,
                alt=img.get("alt"),
                title=img.get("title"),
            )

            # Check if base64 encoded
            if src.startswith("data:"):
                image.is_base64 = True
                # Extract mime type and data
                match = re.match(r"data:([^;]+);base64,(.+)", src)
                if match:
                    image.mime_type = match.group(1)
                    image.base64_data = match.group(2)

            # Extract dimensions
            if img.get("width"):
                try:
                    image.width = int(img["width"])
                except (ValueError, TypeError):
                    pass
            if img.get("height"):
                try:
                    image.height = int(img["height"])
                except (ValueError, TypeError):
                    pass

            images.append(image)

        return images

    def _extract_attachments(self, soup: BeautifulSoup) -> List[ParsedAttachment]:
        """Extract attachment references from document.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of parsed attachments
        """
        attachments = []
        for link in soup.find_all("a", href=True):
            href = link["href"]

            # Skip anchors and mailto links
            if href.startswith(("#", "mailto:", "javascript:")):
                continue

            attachment = ParsedAttachment(
                href=href,
                text=link.get_text(strip=True),
            )

            # Check if external link
            if href.startswith(("http://", "https://", "//")):
                attachment.is_external = True
            else:
                # Try to extract filename
                filename = Path(href).name
                if filename:
                    attachment.filename = filename

            # Only add non-external links as attachments
            if not attachment.is_external:
                attachments.append(attachment)

        return attachments

    def _extract_tables(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract tables from document.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of table data
        """
        tables = []
        for table in soup.find_all("table"):
            table_data = {
                "headers": [],
                "rows": [],
                "caption": None,
            }

            # Extract caption
            caption = table.find("caption")
            if caption:
                table_data["caption"] = caption.get_text(strip=True)

            # Extract headers
            thead = table.find("thead")
            if thead:
                for th in thead.find_all("th"):
                    table_data["headers"].append(th.get_text(strip=True))
            else:
                # Try first row
                first_row = table.find("tr")
                if first_row:
                    for th in first_row.find_all("th"):
                        table_data["headers"].append(th.get_text(strip=True))

            # Extract rows
            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                row = []
                for td in tr.find_all(["td", "th"]):
                    row.append(td.get_text(strip=True))
                if row and (not table_data["headers"] or row != table_data["headers"]):
                    table_data["rows"].append(row)

            if table_data["rows"] or table_data["headers"]:
                tables.append(table_data)

        return tables

    def _extract_lists(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract lists from document.

        Args:
            soup: BeautifulSoup object

        Returns:
            List of list data
        """
        lists = []
        for list_tag in soup.find_all(["ol", "ul"]):
            list_data = {
                "type": "ordered" if list_tag.name == "ol" else "unordered",
                "items": [],
            }

            for li in list_tag.find_all("li", recursive=False):
                # Extract text and nested lists
                item = {"text": "", "subitems": []}

                # Get direct text
                for child in li.children:
                    if isinstance(child, NavigableString):
                        item["text"] += str(child).strip()
                    elif isinstance(child, Tag) and child.name not in ["ol", "ul"]:
                        item["text"] += child.get_text(strip=True)

                # Get nested lists
                for nested in li.find_all(["ol", "ul"], recursive=False):
                    for nested_li in nested.find_all("li"):
                        item["subitems"].append(nested_li.get_text(strip=True))

                if item["text"] or item["subitems"]:
                    list_data["items"].append(item)

            if list_data["items"]:
                lists.append(list_data)

        return lists

    def _extract_metadata(
        self,
        soup: BeautifulSoup,
        document_type: DocumentType,
    ) -> Dict[str, Any]:
        """Extract metadata from document.

        Args:
            soup: BeautifulSoup object
            document_type: Detected document type

        Returns:
            Metadata dictionary
        """
        metadata = {
            "document_type": document_type.value,
            "has_images": len(soup.find_all("img")) > 0,
            "has_tables": len(soup.find_all("table")) > 0,
            "has_lists": len(soup.find_all(["ol", "ul"])) > 0,
            "has_code": len(soup.find_all(["code", "pre"])) > 0,
        }

        # Extract Scribe metadata if present
        if document_type == DocumentType.STEP_BY_STEP:
            steps = soup.find_all(class_="scribe-step")
            metadata["scribe_steps"] = len(steps)

        # Extract template placeholders if present
        if document_type == DocumentType.TEMPLATE:
            placeholders = re.findall(r"\[([A-Z_]+)\]", str(soup))
            metadata["template_placeholders"] = list(set(placeholders))

        return metadata

    def validate_document(self, document: ParsedDocument) -> List[str]:
        """Validate a parsed document.

        Args:
            document: Parsed document

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not document.document_id:
            errors.append("Document ID is missing")

        if not document.title:
            errors.append("Document title is missing")

        if not document.content_html and not document.content_text:
            errors.append("Document has no content")

        if document.content_hash == "":
            errors.append("Content hash not calculated")

        # Check for malformed images
        for i, img in enumerate(document.images):
            if img.is_base64 and not img.base64_data:
                errors.append(f"Image {i} has base64 flag but no data")

        return errors