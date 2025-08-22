"""SuperOps GraphQL API client."""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from migrator.config import SuperOpsConfig
from migrator.logging import get_logger


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: int, per: float = 60.0) -> None:
        """Initialize rate limiter.

        Args:
            rate: Number of allowed requests
            per: Time period in seconds (default 60 for per minute)
        """
        self.rate = rate
        self.per = per
        self.tokens = rate
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            while self.tokens <= 0:
                now = time.monotonic()
                elapsed = now - self.updated_at
                
                # Calculate tokens to add based on elapsed time
                tokens_to_add = elapsed * (self.rate / self.per)
                self.tokens = min(self.rate, self.tokens + tokens_to_add)
                self.updated_at = now
                
                if self.tokens <= 0:
                    # Wait for next token
                    wait_time = (1.0 / (self.rate / self.per))
                    await asyncio.sleep(wait_time)
            
            self.tokens -= 1


class GraphQLError(Exception):
    """GraphQL API error."""

    def __init__(self, message: str, errors: Optional[List[Dict[str, Any]]] = None) -> None:
        """Initialize GraphQL error.

        Args:
            message: Error message
            errors: GraphQL errors from response
        """
        super().__init__(message)
        self.errors = errors or []


class SuperOpsGraphQLClient:
    """SuperOps GraphQL API client with rate limiting and retry logic."""

    # GraphQL queries and mutations
    QUERIES = {
        "getKbItem": """
            query GetKbItem($id: ID!) {
                getKbItem(id: $id) {
                    id
                    title
                    content
                    category {
                        id
                        name
                    }
                    tags
                    createdAt
                    updatedAt
                }
            }
        """,
        "getKbItems": """
            query GetKbItems($page: Int, $perPage: Int, $categoryId: ID) {
                getKbItems(page: $page, perPage: $perPage, categoryId: $categoryId) {
                    items {
                        id
                        title
                        category {
                            id
                            name
                        }
                        tags
                        createdAt
                        updatedAt
                    }
                    totalCount
                    page
                    perPage
                }
            }
        """,
        "getKbItems": """
            query GetKbItems($page: Int, $pageSize: Int) {
                getKbItems(listInfo: {page: $page, pageSize: $pageSize}) {
                    items {
                        itemId
                        name
                        itemType
                        description
                    }
                    listInfo {
                        page
                        pageSize
                        totalCount
                    }
                }
            }
        """,
    }

    MUTATIONS = {
        "createKbArticle": """
            mutation CreateKbArticle($input: CreateKbArticleInput!) {
                createKbArticle(input: $input) {
                    itemId
                    name
                }
            }
        """,
        "updateKbArticle": """
            mutation UpdateKbArticle($input: UpdateKbArticleInput!) {
                updateKbArticle(input: $input) {
                    itemId
                    name
                }
            }
        """,
        "createKbCollection": """
            mutation CreateKbCollection($input: CreateKbCollectionInput!) {
                createKbCollection(input: $input) {
                    itemId
                    name
                }
            }
        """,
        "deleteKbArticle": """
            mutation DeleteKbArticle($input: DeleteKbArticleInput!) {
                deleteKbArticle(input: $input) {
                    success
                }
            }
        """,
    }

    def __init__(self, config: SuperOpsConfig) -> None:
        """Initialize GraphQL client.

        Args:
            config: SuperOps configuration
        """
        self.config = config
        self.logger = get_logger("graphql_client")
        self.rate_limiter = RateLimiter(config.rate_limit, per=60.0)
        self._client: Optional[httpx.AsyncClient] = None
        self._categories_cache: Dict[str, str] = {}  # name -> id

    async def __aenter__(self) -> "SuperOpsGraphQLClient":
        """Enter async context."""
        # Don't use base_url for httpx client, we'll use full URL in post
        self._client = httpx.AsyncClient(
            headers=self._get_headers(),
            timeout=httpx.Timeout(self.config.timeout),
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
            "Content-Type": "application/json",
        }

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
    )
    async def _execute(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        operation_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute GraphQL query or mutation.

        Args:
            query: GraphQL query or mutation
            variables: Query variables
            operation_name: Operation name for logging

        Returns:
            Response data

        Raises:
            GraphQLError: If GraphQL errors occur
            httpx.HTTPError: If network errors occur
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Rate limiting
        await self.rate_limiter.acquire()

        # Prepare request
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        # Log request
        start_time = time.monotonic()
        self.logger.debug(
            "graphql_request",
            operation=operation_name,
            variables=variables,
        )

        try:
            # Execute request
            # The full URL should be the base URL directly for SuperOps
            response = await self._client.post(self.config.base_url, json=payload)
            response.raise_for_status()

            # Parse response
            data = response.json()
            duration_ms = (time.monotonic() - start_time) * 1000

            # Check for errors
            if "errors" in data:
                self.logger.error(
                    "graphql_errors",
                    operation=operation_name,
                    errors=data["errors"],
                    duration_ms=duration_ms,
                )
                raise GraphQLError(
                    f"GraphQL errors in {operation_name}",
                    errors=data["errors"],
                )

            self.logger.debug(
                "graphql_success",
                operation=operation_name,
                duration_ms=duration_ms,
            )

            return data.get("data", {})

        except httpx.HTTPStatusError as e:
            self.logger.error(
                "graphql_http_error",
                operation=operation_name,
                status_code=e.response.status_code,
                detail=e.response.text,
            )
            
            # Parse error response if possible
            try:
                error_data = e.response.json()
                if "errors" in error_data:
                    raise GraphQLError(
                        f"HTTP {e.response.status_code}: {operation_name}",
                        errors=error_data["errors"],
                    )
            except (json.JSONDecodeError, KeyError):
                pass
            
            raise

    async def test_connection(self) -> bool:
        """Test API connectivity.

        Returns:
            True if connection successful
        """
        try:
            # Try to fetch categories as a simple test
            await self.get_kb_categories()
            return True
        except Exception as e:
            self.logger.error("connection_test_failed", error=str(e))
            return False

    async def get_kb_categories(self) -> Dict[str, Any]:
        """Get all Knowledge Base collections (categories).

        Returns:
            Dictionary with categories list
        """
        # Get collections (which act as categories in SuperOps)
        data = await self._execute(
            self.QUERIES["getKbItems"],
            variables={"page": 1, "pageSize": 100},
            operation_name="getKbItems",
        )
        
        # Filter for collections only (not articles)
        all_items = data.get("getKbItems", {}).get("items", [])
        collections = [item for item in all_items if item.get("itemType") == "COLLECTION"]
        
        # Update cache with collections
        for collection in collections:
            self._categories_cache[collection.get("name", "")] = collection.get("itemId", "")

        return {"categories": collections}

    async def create_kb_category(
        self,
        name: str,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Knowledge Base collection (category).

        Args:
            name: Collection name
            description: Collection description
            parent_id: Parent collection ID

        Returns:
            Created collection
        """
        input_data = {
            "name": name,
        }
        
        if parent_id:
            input_data["parent"] = {"itemId": parent_id}

        variables = {
            "input": input_data
        }

        data = await self._execute(
            self.MUTATIONS["createKbCollection"],
            variables=variables,
            operation_name="createKbCollection",
        )

        collection = data.get("createKbCollection", {})
        
        # Update cache
        if collection:
            self._categories_cache[collection.get("name", name)] = collection.get("itemId", "")

        return collection

    async def get_or_create_category(self, name: str) -> str:
        """Get existing category ID or create new one.

        Args:
            name: Category name

        Returns:
            Category ID
        """
        # Check cache first
        if name in self._categories_cache:
            return self._categories_cache[name]

        # Fetch categories
        categories_response = await self.get_kb_categories()
        categories = categories_response.get("categories", [])
        
        # Check if exists
        for category in categories:
            if category.get("name") == name:
                return category.get("itemId")

        # Create new category (collection)
        category = await self.create_kb_category(name)
        return category.get("itemId", "")

    async def create_kb_article(
        self,
        title: str,
        content: str,
        category_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a Knowledge Base article.

        Args:
            title: Article title
            content: Article content (HTML)
            category_id: Category ID
            tags: List of tags
            attachments: List of attachment data
            metadata: Additional metadata

        Returns:
            Created article

        Raises:
            GraphQLError: If creation fails
        """
        # SuperOps requires parent collection for articles
        if not category_id:
            # Get or create a default collection
            category_id = await self.get_or_create_category("General")
        
        # Build input for createKbArticle with CORRECT visibility structure
        # This configuration makes the article visible to all requesters and technicians
        input_data = {
            "name": title,
            "content": content,
            "parent": {"itemId": category_id},
            "status": "PUBLISHED",  # Default to published
            "visibility": {
                "added": [
                    {
                        # Make visible to all requesters (clients)
                        "portalType": "REQUESTER",
                        "clientSharedType": "AllClients",
                        "siteSharedType": "AllSites",
                        "userRoleSharedType": "AllRoles"
                    },
                    {
                        # Make visible to all technicians
                        "portalType": "TECHNICIAN",
                        "userSharedType": "AllUsers",
                        "groupSharedType": "AllGroups"
                    }
                ]
            },
            "loginRequired": False
        }

        variables = {
            "input": input_data
        }

        data = await self._execute(
            self.MUTATIONS["createKbArticle"],
            variables=variables,
            operation_name="createKbArticle",
        )

        article = data.get("createKbArticle", {})
        
        if not article:
            raise GraphQLError("Failed to create article: Empty response")

        self.logger.info(
            "article_created",
            article_id=article.get("itemId"),
            title=title,
        )

        return article

    async def update_kb_article(
        self,
        article_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        category_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update a Knowledge Base article.

        Args:
            article_id: Article ID to update
            title: New title
            content: New content
            category_id: New category ID
            tags: New tags

        Returns:
            Updated article
        """
        input_data = {
            "itemId": article_id,
        }

        # Add fields to update
        if title is not None:
            input_data["name"] = title
        if content is not None:
            input_data["content"] = content
        if category_id is not None:
            input_data["parent"] = {"itemId": category_id}

        if len(input_data) == 1:  # Only has itemId
            raise ValueError("No fields to update")

        variables = {
            "input": input_data
        }

        data = await self._execute(
            self.MUTATIONS["updateKbArticle"],
            variables=variables,
            operation_name="updateKbArticle",
        )

        return data.get("updateKbArticle", {})

    async def get_kb_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Get a Knowledge Base article by ID.

        Args:
            article_id: Article ID

        Returns:
            Article data or None
        """
        variables = {"id": article_id}

        try:
            data = await self._execute(
                self.QUERIES["getKbItem"],
                variables=variables,
                operation_name="getKbItem",
            )
            return data.get("getKbItem")
        except GraphQLError:
            return None

    async def get_kb_articles(
        self,
        page: int = 1,
        per_page: int = 50,
        category_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated Knowledge Base articles.

        Args:
            page: Page number
            per_page: Items per page
            category_id: Filter by category

        Returns:
            Paginated response with articles
        """
        variables = {
            "page": page,
            "pageSize": per_page,
        }

        data = await self._execute(
            self.QUERIES["getKbItems"],
            variables=variables,
            operation_name="getKbItems",
        )

        response = data.get("getKbItems", {})
        
        # If category_id is specified, filter results client-side
        if category_id and response.get("items"):
            # Filter items that have this parent
            filtered_items = []
            for item in response["items"]:
                # This is a simplification - may need to check parent chain
                if item.get("parent", {}).get("itemId") == category_id:
                    filtered_items.append(item)
            response["items"] = filtered_items
        
        return response

    async def delete_kb_article(self, article_id: str) -> bool:
        """Delete a Knowledge Base article.

        Args:
            article_id: Article ID to delete

        Returns:
            True if successful
        """
        variables = {
            "input": {
                "itemId": article_id
            }
        }

        data = await self._execute(
            self.MUTATIONS["deleteKbArticle"],
            variables=variables,
            operation_name="deleteKbArticle",
        )

        result = data.get("deleteKbArticle", {})
        return result.get("success", False)

    async def check_article_exists(self, title: str) -> Optional[str]:
        """Check if article with title exists.

        Args:
            title: Article title to check

        Returns:
            Article ID if exists, None otherwise
        """
        # This is a simplified check - in production you'd want
        # a more efficient server-side search
        page = 1
        while True:
            response = await self.get_kb_articles(page=page, per_page=100)
            
            if not response.get("items"):
                break

            for article in response["items"]:
                # Check for articles (not collections) with matching name
                if article.get("itemType") != "COLLECTION" and article.get("name") == title:
                    return article.get("itemId")

            list_info = response.get("listInfo", {})
            if page * 100 >= list_info.get("totalCount", 0):
                break

            page += 1

        return None