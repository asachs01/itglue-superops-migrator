"""SuperOps REST API client for file attachments."""

import asyncio
import base64
import hashlib
import mimetypes
import time
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

import aiofiles
import httpx
import magic
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from migrator.config import SuperOpsConfig
from migrator.logging import get_logger


class AttachmentError(Exception):
    """Attachment upload error."""
    pass


class AttachmentUploadResult:
    """Result of attachment upload."""

    def __init__(
        self,
        success: bool,
        filename: str,
        original_filename: str,
        file_size: int,
        url: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Initialize upload result.

        Args:
            success: Whether upload was successful
            filename: Server filename
            original_filename: Original filename
            file_size: File size in bytes
            url: Download URL if available
            error: Error message if failed
        """
        self.success = success
        self.filename = filename
        self.original_filename = original_filename
        self.file_size = file_size
        self.url = url
        self.error = error


class SuperOpsAttachmentClient:
    """REST client for SuperOps attachment uploads."""

    # Maximum file size (50MB default)
    MAX_FILE_SIZE = 50 * 1024 * 1024

    # Chunk size for large file uploads (5MB)
    CHUNK_SIZE = 5 * 1024 * 1024

    # Supported image formats for optimization
    IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    def __init__(self, config: SuperOpsConfig, max_file_size: Optional[int] = None) -> None:
        """Initialize attachment client.

        Args:
            config: SuperOps configuration
            max_file_size: Maximum file size override
        """
        self.config = config
        self.max_file_size = max_file_size or self.MAX_FILE_SIZE
        self.logger = get_logger("attachment_client")
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiter = asyncio.Semaphore(config.rate_limit // 10)  # Limit concurrent uploads
        self._file_cache: Dict[str, str] = {}  # hash -> url

    async def __aenter__(self) -> "SuperOpsAttachmentClient":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=self._get_headers(),
            timeout=httpx.Timeout(60.0, connect=10.0),  # Longer timeout for uploads
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers.

        Returns:
            Headers dictionary
        """
        return {
            "Authorization": f"Bearer {self.config.api_token.get_secret_value()}",
            "CustomerSubDomain": self.config.subdomain,
        }

    async def upload_file(
        self,
        file_path: Path,
        module: str = "kb",
        optimize_images: bool = True,
    ) -> AttachmentUploadResult:
        """Upload a file from disk.

        Args:
            file_path: Path to file
            module: Upload module (e.g., 'kb' for Knowledge Base)
            optimize_images: Whether to optimize images before upload

        Returns:
            Upload result
        """
        if not file_path.exists():
            return AttachmentUploadResult(
                success=False,
                filename=file_path.name,
                original_filename=file_path.name,
                file_size=0,
                error=f"File not found: {file_path}",
            )

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            return AttachmentUploadResult(
                success=False,
                filename=file_path.name,
                original_filename=file_path.name,
                file_size=file_size,
                error=f"File too large: {file_size} bytes (max: {self.max_file_size})",
            )

        # Calculate file hash for deduplication
        file_hash = await self._calculate_file_hash(file_path)
        
        # Check cache
        if file_hash in self._file_cache:
            self.logger.debug(
                "file_cached",
                filename=file_path.name,
                hash=file_hash,
            )
            return AttachmentUploadResult(
                success=True,
                filename=file_path.name,
                original_filename=file_path.name,
                file_size=file_size,
                url=self._file_cache[file_hash],
            )

        # Optimize image if applicable
        upload_path = file_path
        if optimize_images and file_path.suffix.lower() in self.IMAGE_FORMATS:
            optimized = await self._optimize_image(file_path)
            if optimized:
                upload_path = optimized

        # Upload file
        try:
            if file_size > self.CHUNK_SIZE:
                result = await self._upload_chunked(upload_path, module)
            else:
                result = await self._upload_simple(upload_path, module)

            # Cache successful upload
            if result.success and result.url:
                self._file_cache[file_hash] = result.url

            return result

        finally:
            # Clean up optimized image
            if upload_path != file_path and upload_path.exists():
                upload_path.unlink()

    async def upload_bytes(
        self,
        data: bytes,
        filename: str,
        module: str = "kb",
        mime_type: Optional[str] = None,
    ) -> AttachmentUploadResult:
        """Upload binary data.

        Args:
            data: Binary data to upload
            filename: Filename for the upload
            module: Upload module
            mime_type: MIME type of the data

        Returns:
            Upload result
        """
        file_size = len(data)
        
        # Check size
        if file_size > self.max_file_size:
            return AttachmentUploadResult(
                success=False,
                filename=filename,
                original_filename=filename,
                file_size=file_size,
                error=f"Data too large: {file_size} bytes",
            )

        # Detect MIME type if not provided
        if not mime_type:
            mime_type = self._detect_mime_type(data, filename)

        # Calculate hash for deduplication
        data_hash = hashlib.sha256(data).hexdigest()
        
        # Check cache
        if data_hash in self._file_cache:
            return AttachmentUploadResult(
                success=True,
                filename=filename,
                original_filename=filename,
                file_size=file_size,
                url=self._file_cache[data_hash],
            )

        # Upload
        result = await self._upload_bytes_internal(data, filename, module, mime_type)
        
        # Cache successful upload
        if result.success and result.url:
            self._file_cache[data_hash] = result.url

        return result

    async def upload_base64_image(
        self,
        base64_data: str,
        filename: str,
        mime_type: str,
        module: str = "kb",
    ) -> AttachmentUploadResult:
        """Upload base64 encoded image.

        Args:
            base64_data: Base64 encoded image data
            filename: Filename for the image
            mime_type: MIME type of the image
            module: Upload module

        Returns:
            Upload result
        """
        try:
            # Decode base64
            image_data = base64.b64decode(base64_data)
            
            # Upload as bytes
            return await self.upload_bytes(image_data, filename, module, mime_type)

        except Exception as e:
            self.logger.error(
                "base64_decode_error",
                filename=filename,
                error=str(e),
            )
            return AttachmentUploadResult(
                success=False,
                filename=filename,
                original_filename=filename,
                file_size=0,
                error=f"Failed to decode base64: {e}",
            )

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
    )
    async def _upload_simple(self, file_path: Path, module: str) -> AttachmentUploadResult:
        """Simple file upload for small files.

        Args:
            file_path: Path to file
            module: Upload module

        Returns:
            Upload result
        """
        if not self._client:
            raise RuntimeError("Client not initialized")

        async with self._rate_limiter:
            start_time = time.monotonic()
            
            try:
                # Prepare multipart form
                async with aiofiles.open(file_path, "rb") as f:
                    file_data = await f.read()

                mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                
                files = {
                    "files": (file_path.name, file_data, mime_type),
                }
                
                data = {
                    "module": module,
                }

                # Upload
                response = await self._client.post(
                    "/upload",
                    files=files,
                    data=data,
                )
                response.raise_for_status()

                # Parse response
                result = response.json()
                duration_ms = (time.monotonic() - start_time) * 1000

                self.logger.info(
                    "file_uploaded",
                    filename=file_path.name,
                    size=len(file_data),
                    duration_ms=duration_ms,
                )

                # Extract first file result
                if result.get("data") and len(result["data"]) > 0:
                    file_info = result["data"][0]
                    return AttachmentUploadResult(
                        success=True,
                        filename=file_info.get("fileName", file_path.name),
                        original_filename=file_info.get("originalFileName", file_path.name),
                        file_size=file_info.get("fileSize", len(file_data)),
                        url=file_info.get("url"),
                    )
                else:
                    return AttachmentUploadResult(
                        success=False,
                        filename=file_path.name,
                        original_filename=file_path.name,
                        file_size=len(file_data),
                        error="No file data in response",
                    )

            except httpx.HTTPStatusError as e:
                self.logger.error(
                    "upload_http_error",
                    filename=file_path.name,
                    status_code=e.response.status_code,
                    detail=e.response.text,
                )
                return AttachmentUploadResult(
                    success=False,
                    filename=file_path.name,
                    original_filename=file_path.name,
                    file_size=file_path.stat().st_size,
                    error=f"HTTP {e.response.status_code}",
                )

    async def _upload_chunked(self, file_path: Path, module: str) -> AttachmentUploadResult:
        """Chunked upload for large files.

        Args:
            file_path: Path to file
            module: Upload module

        Returns:
            Upload result
        """
        # For now, fall back to simple upload
        # In production, implement proper chunked upload protocol
        self.logger.warning(
            "chunked_upload_fallback",
            filename=file_path.name,
            size=file_path.stat().st_size,
        )
        return await self._upload_simple(file_path, module)

    async def _upload_bytes_internal(
        self,
        data: bytes,
        filename: str,
        module: str,
        mime_type: str,
    ) -> AttachmentUploadResult:
        """Internal method to upload bytes.

        Args:
            data: Binary data
            filename: Filename
            module: Upload module
            mime_type: MIME type

        Returns:
            Upload result
        """
        if not self._client:
            raise RuntimeError("Client not initialized")

        async with self._rate_limiter:
            try:
                files = {
                    "files": (filename, data, mime_type),
                }
                
                form_data = {
                    "module": module,
                }

                response = await self._client.post(
                    "/upload",
                    files=files,
                    data=form_data,
                )
                response.raise_for_status()

                result = response.json()

                if result.get("data") and len(result["data"]) > 0:
                    file_info = result["data"][0]
                    return AttachmentUploadResult(
                        success=True,
                        filename=file_info.get("fileName", filename),
                        original_filename=file_info.get("originalFileName", filename),
                        file_size=file_info.get("fileSize", len(data)),
                        url=file_info.get("url"),
                    )
                else:
                    return AttachmentUploadResult(
                        success=False,
                        filename=filename,
                        original_filename=filename,
                        file_size=len(data),
                        error="No file data in response",
                    )

            except Exception as e:
                self.logger.error(
                    "upload_error",
                    filename=filename,
                    error=str(e),
                )
                return AttachmentUploadResult(
                    success=False,
                    filename=filename,
                    original_filename=filename,
                    file_size=len(data),
                    error=str(e),
                )

    async def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of hash
        """
        hasher = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            while chunk := await f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    async def _optimize_image(self, file_path: Path) -> Optional[Path]:
        """Optimize image for upload.

        Args:
            file_path: Path to image

        Returns:
            Path to optimized image or None
        """
        try:
            # Open image
            with Image.open(file_path) as img:
                # Convert RGBA to RGB if needed
                if img.mode == "RGBA":
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background

                # Resize if too large
                max_dimension = 2048
                if img.width > max_dimension or img.height > max_dimension:
                    img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

                # Save optimized version
                optimized_path = file_path.parent / f"optimized_{file_path.name}"
                img.save(
                    optimized_path,
                    format="JPEG",
                    quality=85,
                    optimize=True,
                )

                # Check if optimization actually reduced size
                if optimized_path.stat().st_size < file_path.stat().st_size:
                    self.logger.debug(
                        "image_optimized",
                        original=file_path.name,
                        original_size=file_path.stat().st_size,
                        optimized_size=optimized_path.stat().st_size,
                    )
                    return optimized_path
                else:
                    optimized_path.unlink()
                    return None

        except Exception as e:
            self.logger.warning(
                "image_optimization_failed",
                filename=file_path.name,
                error=str(e),
            )
            return None

    def _detect_mime_type(self, data: bytes, filename: str) -> str:
        """Detect MIME type from data and filename.

        Args:
            data: Binary data
            filename: Filename

        Returns:
            MIME type
        """
        # Try to detect from data
        try:
            mime = magic.from_buffer(data, mime=True)
            if mime:
                return mime
        except Exception:
            pass

        # Fall back to filename
        mime_type = mimetypes.guess_type(filename)[0]
        return mime_type or "application/octet-stream"

    async def batch_upload(
        self,
        files: List[Path],
        module: str = "kb",
        max_concurrent: int = 3,
    ) -> List[AttachmentUploadResult]:
        """Upload multiple files concurrently.

        Args:
            files: List of file paths
            module: Upload module
            max_concurrent: Maximum concurrent uploads

        Returns:
            List of upload results
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def upload_with_limit(file_path: Path) -> AttachmentUploadResult:
            async with semaphore:
                return await self.upload_file(file_path, module)

        tasks = [upload_with_limit(f) for f in files]
        return await asyncio.gather(*tasks)