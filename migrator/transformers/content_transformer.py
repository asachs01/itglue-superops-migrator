"""Content transformation engine for ITGlue to SuperOps migration."""

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from migrator.api.rest_client import SuperOpsAttachmentClient
from migrator.logging import get_logger
from migrator.parsers.html_parser import ParsedDocument, ParsedImage


class TransformedAttachment(BaseModel):
    """Transformed attachment ready for SuperOps."""

    filename: str
    original_path: str
    superops_url: Optional[str] = None
    size_bytes: int
    mime_type: Optional[str] = None
    needs_upload: bool = True
    is_embedded: bool = False
    base64_data: Optional[str] = None


class TransformedDocument(BaseModel):
    """Document transformed for SuperOps."""

    title: str
    content_html: str
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    attachments: List[TransformedAttachment] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    validation_errors: List[str] = Field(default_factory=list)


class ContentTransformer:
    """Transform ITGlue content to SuperOps format."""

    # HTML elements to preserve
    PRESERVE_TAGS = {
        "p", "br", "div", "span",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li",
        "table", "thead", "tbody", "tr", "th", "td",
        "a", "img",
        "strong", "b", "em", "i", "u",
        "code", "pre", "blockquote",
    }

    # ITGlue to SuperOps category mapping
    CATEGORY_MAPPING = {
        "Applications": "Software & Applications",
        "Contracts": "Legal & Contracts",
        "CrowdStrike": "Security Tools",
        "AutomicUC4": "Automation",
        "Documentation": "General Documentation",
        "Cummins": "Client Documentation",
        "Catepillar": "Client Documentation",
    }

    def __init__(self, attachments_base_path: Path) -> None:
        """Initialize content transformer.

        Args:
            attachments_base_path: Base path for attachments
        """
        self.attachments_base_path = attachments_base_path
        self.logger = get_logger("content_transformer")
        self._attachment_client: Optional[SuperOpsAttachmentClient] = None

    def set_attachment_client(self, client: SuperOpsAttachmentClient) -> None:
        """Set attachment client for URL replacement.

        Args:
            client: Attachment client instance
        """
        self._attachment_client = client

    def transform_document(
        self,
        parsed_doc: ParsedDocument,
        organization: Optional[str] = None,
    ) -> TransformedDocument:
        """Transform parsed ITGlue document to SuperOps format.

        Args:
            parsed_doc: Parsed ITGlue document
            organization: Organization name

        Returns:
            Transformed document
        """
        self.logger.debug(
            "transforming_document",
            document_id=parsed_doc.document_id,
            title=parsed_doc.title,
        )

        # Clean and prepare title
        title = self._clean_title(parsed_doc.title)

        # Transform HTML content
        content_html = self._transform_html(parsed_doc.content_html)

        # Extract category
        category = self._determine_category(parsed_doc, organization)

        # Generate tags
        tags = self._generate_tags(parsed_doc, organization)

        # Process attachments and images
        attachments = self._process_attachments(parsed_doc)

        # Update image references in content
        content_html = self._update_image_references(content_html, attachments)

        # Build metadata
        metadata = self._build_metadata(parsed_doc, organization)

        # Validate transformation
        validation_errors = self._validate_transformation(
            title, content_html, attachments
        )

        transformed = TransformedDocument(
            title=title,
            content_html=content_html,
            category=category,
            tags=tags,
            attachments=attachments,
            metadata=metadata,
            validation_errors=validation_errors,
        )

        self.logger.info(
            "document_transformed",
            document_id=parsed_doc.document_id,
            title=title,
            category=category,
            tags_count=len(tags),
            attachments_count=len(attachments),
            errors_count=len(validation_errors),
        )

        return transformed

    def _clean_title(self, title: str) -> str:
        """Clean and normalize document title.

        Args:
            title: Original title

        Returns:
            Cleaned title
        """
        # Remove document ID patterns
        title = re.sub(r"^DOC-\d+-\d+\s*", "", title)
        
        # Remove file extensions
        title = re.sub(r"\.(html?|docx?|pdf|txt)$", "", title, flags=re.IGNORECASE)
        
        # Remove special markers
        title = title.replace("[TEMPLATE]", "").replace("[DELETEME]", "")
        
        # Normalize whitespace
        title = " ".join(title.split())
        
        # Ensure minimum length
        if len(title) < 3:
            title = f"Document {uuid.uuid4().hex[:8]}"

        # Truncate if too long
        if len(title) > 255:
            title = title[:252] + "..."

        return title

    def _transform_html(self, html: str) -> str:
        """Transform HTML content for SuperOps.

        Args:
            html: Original HTML content

        Returns:
            Transformed HTML
        """
        if not html:
            return "<p>No content available.</p>"

        soup = BeautifulSoup(html, "lxml")

        # Remove unwanted tags
        for tag in soup.find_all():
            if tag.name not in self.PRESERVE_TAGS:
                if tag.name in ["script", "style", "meta", "link"]:
                    tag.decompose()
                else:
                    # Unwrap tag but keep content
                    tag.unwrap()

        # Clean attributes
        for tag in soup.find_all():
            # Keep only essential attributes
            allowed_attrs = []
            if tag.name == "a":
                allowed_attrs = ["href", "target", "rel"]
            elif tag.name == "img":
                allowed_attrs = ["src", "alt", "title", "width", "height"]
            elif tag.name in ["td", "th"]:
                allowed_attrs = ["colspan", "rowspan"]
            elif tag.name == "table":
                allowed_attrs = ["border", "cellpadding", "cellspacing"]

            # Remove unwanted attributes
            for attr in list(tag.attrs.keys()):
                if attr not in allowed_attrs and not attr.startswith("data-"):
                    del tag[attr]

        # Fix relative links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith(("http://", "https://", "mailto:", "#")):
                # Convert to placeholder
                link["href"] = f"#attachment:{href}"

        # Clean up empty paragraphs
        for p in soup.find_all("p"):
            if not p.get_text(strip=True) and not p.find("img"):
                p.decompose()

        # Add styling to tables
        for table in soup.find_all("table"):
            if "border" not in table.attrs:
                table["border"] = "1"
            if "cellpadding" not in table.attrs:
                table["cellpadding"] = "5"

        # Convert Scribe step formatting
        for step in soup.find_all(class_="scribe-step"):
            # Convert to ordered list item
            step.name = "li"
            step["class"] = []

        # Wrap steps in ordered list
        steps = soup.find_all("li", class_=[])
        if steps and len(steps) > 1:
            ol = soup.new_tag("ol")
            first_step = steps[0]
            first_step.insert_before(ol)
            for step in steps:
                ol.append(step.extract())

        return str(soup)

    def _determine_category(
        self,
        parsed_doc: ParsedDocument,
        organization: Optional[str] = None,
    ) -> Optional[str]:
        """Determine SuperOps category for document.

        Args:
            parsed_doc: Parsed document
            organization: Organization name

        Returns:
            Category name or None
        """
        # Check organization-based category
        if organization and organization in self.CATEGORY_MAPPING:
            return self.CATEGORY_MAPPING[organization]

        # Check document type
        doc_type_categories = {
            "procedural": "Procedures & SOPs",
            "template": "Templates",
            "step_by_step": "How-To Guides",
            "information": "Reference Documentation",
        }
        
        if parsed_doc.document_type.value in doc_type_categories:
            return doc_type_categories[parsed_doc.document_type.value]

        # Check title patterns
        title_lower = parsed_doc.title.lower()
        
        if "onboarding" in title_lower:
            return "Onboarding"
        elif "troubleshoot" in title_lower:
            return "Troubleshooting"
        elif "setup" in title_lower or "install" in title_lower:
            return "Setup & Installation"
        elif "backup" in title_lower or "restore" in title_lower:
            return "Backup & Recovery"
        elif "security" in title_lower or "password" in title_lower:
            return "Security"
        elif "network" in title_lower or "vpn" in title_lower:
            return "Networking"

        return "General Documentation"

    def _generate_tags(
        self,
        parsed_doc: ParsedDocument,
        organization: Optional[str] = None,
    ) -> List[str]:
        """Generate tags for document.

        Args:
            parsed_doc: Parsed document
            organization: Organization name

        Returns:
            List of tags
        """
        tags = []

        # Add organization as tag
        if organization:
            tags.append(organization.replace(" ", "-").lower())

        # Add document type
        if parsed_doc.document_type.value != "unknown":
            tags.append(parsed_doc.document_type.value)

        # Extract technology tags from title
        title_lower = parsed_doc.title.lower()
        tech_keywords = [
            "azure", "aws", "office365", "o365", "microsoft", "google",
            "vpn", "firewall", "fortigate", "cisco", "ubiquiti",
            "active-directory", "ad", "exchange", "sharepoint",
            "backup", "datto", "veeam", "acronis",
            "antivirus", "sentinel", "crowdstrike", "defender",
            "quickbooks", "sage", "erp", "crm",
        ]

        for keyword in tech_keywords:
            if keyword in title_lower or keyword in parsed_doc.content_text.lower()[:500]:
                tags.append(keyword)

        # Add metadata tags
        if parsed_doc.metadata.get("has_images"):
            tags.append("illustrated")
        if parsed_doc.metadata.get("has_code"):
            tags.append("technical")
        if parsed_doc.metadata.get("scribe_steps"):
            tags.append("step-by-step")

        # Deduplicate and limit
        tags = list(set(tags))[:10]  # Limit to 10 tags

        return tags

    def _process_attachments(self, parsed_doc: ParsedDocument) -> List[TransformedAttachment]:
        """Process document attachments and images.

        Args:
            parsed_doc: Parsed document

        Returns:
            List of transformed attachments
        """
        attachments = []

        # Process embedded images
        for img in parsed_doc.images:
            if img.is_base64:
                # Create attachment for base64 image
                filename = f"embedded_image_{uuid.uuid4().hex[:8]}.{img.mime_type.split('/')[-1] if img.mime_type else 'png'}"
                
                attachment = TransformedAttachment(
                    filename=filename,
                    original_path=img.src[:50] + "..." if len(img.src) > 50 else img.src,
                    size_bytes=len(img.base64_data) if img.base64_data else 0,
                    mime_type=img.mime_type,
                    needs_upload=True,
                    is_embedded=True,
                    base64_data=img.base64_data,
                )
                attachments.append(attachment)
            else:
                # Process file-based image
                attachment = self._process_file_reference(img.src, is_image=True)
                if attachment:
                    attachments.append(attachment)

        # Process document attachments
        for att in parsed_doc.attachments:
            if not att.is_external:
                attachment = self._process_file_reference(att.href, is_image=False)
                if attachment:
                    attachments.append(attachment)

        return attachments

    def _process_file_reference(
        self,
        reference: str,
        is_image: bool,
    ) -> Optional[TransformedAttachment]:
        """Process a file reference.

        Args:
            reference: File reference (path or URL)
            is_image: Whether this is an image

        Returns:
            Transformed attachment or None
        """
        # Extract path components
        # Pattern: 8250506/docs/19685796/images/30507517
        match = re.match(r"(\d+)/docs/(\d+)/(images|attachments)/(\d+)", reference)
        if match:
            org_id = match.group(1)
            doc_id = match.group(2)
            att_type = match.group(3)
            att_id = match.group(4)

            # Build expected file path
            possible_paths = [
                self.attachments_base_path / f"documents/DOC-{org_id}-{doc_id}/{att_id}",
                self.attachments_base_path / f"documents/{doc_id}/{att_id}",
                self.attachments_base_path / f"{att_type}/{doc_id}/{att_id}",
            ]

            for base_path in possible_paths:
                # Try common extensions
                extensions = [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".docx", ".xlsx", ""]
                for ext in extensions:
                    file_path = base_path.with_suffix(ext)
                    if file_path.exists():
                        return TransformedAttachment(
                            filename=file_path.name,
                            original_path=str(file_path),
                            size_bytes=file_path.stat().st_size,
                            mime_type=self._guess_mime_type(file_path),
                            needs_upload=True,
                            is_embedded=False,
                        )

        # Try as direct path
        file_path = Path(reference)
        if file_path.exists():
            return TransformedAttachment(
                filename=file_path.name,
                original_path=str(file_path),
                size_bytes=file_path.stat().st_size,
                mime_type=self._guess_mime_type(file_path),
                needs_upload=True,
                is_embedded=False,
            )

        self.logger.warning(
            "attachment_not_found",
            reference=reference,
            is_image=is_image,
        )
        return None

    def _update_image_references(
        self,
        html: str,
        attachments: List[TransformedAttachment],
    ) -> str:
        """Update image references in HTML.

        Args:
            html: HTML content
            attachments: List of attachments

        Returns:
            Updated HTML
        """
        soup = BeautifulSoup(html, "lxml")

        # Build mapping of original paths to SuperOps URLs
        url_map = {}
        for att in attachments:
            if att.superops_url:
                # Map various possible references
                url_map[att.original_path] = att.superops_url
                url_map[att.filename] = att.superops_url

        # Update image sources
        for img in soup.find_all("img"):
            src = img.get("src", "")
            
            # Check if we have a replacement URL
            for original, new_url in url_map.items():
                if original in src or src.endswith(original):
                    img["src"] = new_url
                    break
            else:
                # If no replacement and it's a base64 image, leave it
                if not src.startswith("data:"):
                    # Replace with placeholder
                    img["src"] = f"#pending-upload:{src}"
                    img["alt"] = img.get("alt", "Image pending upload")

        # Update attachment links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("#attachment:"):
                # Extract original reference
                original_ref = href.replace("#attachment:", "")
                
                # Check if we have a replacement URL
                for att in attachments:
                    if original_ref in att.original_path or original_ref == att.filename:
                        if att.superops_url:
                            link["href"] = att.superops_url
                        break

        return str(soup)

    def _build_metadata(
        self,
        parsed_doc: ParsedDocument,
        organization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build metadata for transformed document.

        Args:
            parsed_doc: Parsed document
            organization: Organization name

        Returns:
            Metadata dictionary
        """
        metadata = {
            "source": "ITGlue",
            "original_id": parsed_doc.document_id,
            "document_type": parsed_doc.document_type.value,
            "content_hash": parsed_doc.content_hash,
        }

        if organization:
            metadata["organization"] = organization

        # Add statistics
        metadata["statistics"] = {
            "headings": len(parsed_doc.headings),
            "images": len(parsed_doc.images),
            "attachments": len(parsed_doc.attachments),
            "tables": len(parsed_doc.tables),
            "lists": len(parsed_doc.lists),
        }

        # Add any custom metadata from parsing
        metadata.update(parsed_doc.metadata)

        return metadata

    def _validate_transformation(
        self,
        title: str,
        content_html: str,
        attachments: List[TransformedAttachment],
    ) -> List[str]:
        """Validate transformed document.

        Args:
            title: Document title
            content_html: HTML content
            attachments: List of attachments

        Returns:
            List of validation errors
        """
        errors = []

        # Validate title
        if not title or len(title) < 3:
            errors.append("Title is too short")
        if len(title) > 255:
            errors.append("Title is too long")

        # Validate content
        if not content_html:
            errors.append("Content is empty")
        elif len(content_html) < 10:
            errors.append("Content is too short")
        elif len(content_html) > 1000000:  # 1MB limit
            errors.append("Content is too large")

        # Check for broken references
        soup = BeautifulSoup(content_html, "lxml")
        
        for img in soup.find_all("img", src=True):
            if img["src"].startswith("#pending-upload:"):
                errors.append(f"Unresolved image reference: {img['src']}")

        for link in soup.find_all("a", href=True):
            if link["href"].startswith("#attachment:"):
                errors.append(f"Unresolved attachment reference: {link['href']}")

        # Validate attachments
        for att in attachments:
            if att.needs_upload and not att.is_embedded:
                # Check if file exists
                if not Path(att.original_path).exists():
                    errors.append(f"Attachment file not found: {att.filename}")
            
            if att.size_bytes > 50 * 1024 * 1024:  # 50MB limit
                errors.append(f"Attachment too large: {att.filename} ({att.size_bytes} bytes)")

        return errors

    def _guess_mime_type(self, file_path: Path) -> str:
        """Guess MIME type from file path.

        Args:
            file_path: Path to file

        Returns:
            MIME type
        """
        import mimetypes
        
        mime_type = mimetypes.guess_type(str(file_path))[0]
        return mime_type or "application/octet-stream"

    async def upload_attachments(
        self,
        attachments: List[TransformedAttachment],
    ) -> Dict[str, str]:
        """Upload attachments and get URLs.

        Args:
            attachments: List of attachments to upload

        Returns:
            Mapping of filename to SuperOps URL
        """
        if not self._attachment_client:
            raise RuntimeError("Attachment client not set")

        url_map = {}

        for att in attachments:
            if not att.needs_upload or att.superops_url:
                continue

            try:
                if att.is_embedded and att.base64_data:
                    # Upload base64 image
                    result = await self._attachment_client.upload_base64_image(
                        att.base64_data,
                        att.filename,
                        att.mime_type or "image/png",
                    )
                else:
                    # Upload file
                    file_path = Path(att.original_path)
                    if file_path.exists():
                        result = await self._attachment_client.upload_file(file_path)
                    else:
                        self.logger.error(
                            "attachment_file_not_found",
                            filename=att.filename,
                            path=att.original_path,
                        )
                        continue

                if result.success and result.url:
                    att.superops_url = result.url
                    att.needs_upload = False
                    url_map[att.filename] = result.url
                else:
                    self.logger.error(
                        "attachment_upload_failed",
                        filename=att.filename,
                        error=result.error,
                    )

            except Exception as e:
                self.logger.error(
                    "attachment_upload_error",
                    filename=att.filename,
                    error=str(e),
                    exc_info=e,
                )

        return url_map