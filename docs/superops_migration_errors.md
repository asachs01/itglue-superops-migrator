# SuperOps Knowledge Base Migration - Technical Error Report

## Executive Summary
We are attempting to migrate 673 Knowledge Base articles from ITGlue to SuperOps using the GraphQL API. While we can successfully create categories (collections), article creation fails with internal server errors related to the visibility field configuration.

## Migration Architecture

### Data Flow
1. **Source**: ITGlue HTML exports (673 documents across 35 organizations)
2. **Parser**: BeautifulSoup4 for HTML content extraction
3. **Transformer**: Content sanitization and conversion pipeline
4. **API Client**: GraphQL mutations to SuperOps API
5. **State Management**: SQLite for tracking migration progress

### API Endpoint
- **Base URL**: `https://api.superops.ai/msp`
- **Authentication**: Bearer token + CustomerSubDomain header
- **Protocol**: GraphQL

## Successful Operations

### 1. Category/Collection Creation ✅
```graphql
mutation CreateKbCollection($input: CreateKbCollectionInput!) {
    createKbCollection(input: $input) {
        itemId
        name
    }
}
```

**Working Input**:
```json
{
  "input": {
    "name": "Test Category"
  }
}
```

**Response**: Successfully creates collections with returned itemId

### 2. Listing KB Items ✅
```graphql
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
```

**Response**: Successfully returns all KB collections

## Failed Operations

### Article Creation ❌

#### Schema Requirements (from introspection)
```
CreateKbArticleInput fields:
  name: String!                    # Required
  parent: KBItemIdentifierInput!   # Required
  status: ArticleStatus!           # Required (DRAFT or PUBLISHED)
  content: String!                 # Required
  visibility: CreateDocumentShareInput! # Required - THIS IS THE PROBLEM
  loginRequired: Boolean           # Optional
```

#### Visibility Field Structure
```
CreateDocumentShareInput:
  added: [NewShareDetailsInput]!

NewShareDetailsInput:
  portalType: RoleTypeEnum         # TECHNICIAN or REQUESTER
  accountId: ID
  siteId: ID
  clientSharedType: ClientSharedType
  siteSharedType: SiteSharedType
  userRoleSharedType: UserRoleSharedType
  addedRoleIds: ID
  userSharedType: UserSharedType
  groupSharedType: GroupSharedType
  addedUserIds: ID
  addedGroupIds: ID
```

## Error Patterns

### Test Case 1: Empty Visibility Array
```json
{
  "input": {
    "name": "Test Article 1",
    "content": "<p>This is a test article content.</p>",
    "parent": {"itemId": "7986891993049776128"},
    "status": "PUBLISHED",
    "visibility": {
      "added": []
    },
    "loginRequired": false
  }
}
```
**Error**: `Internal Server Error(s) while executing query`

### Test Case 2: Basic Technician Visibility
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
**Error**: `Internal Server Error(s) while executing query`

### Test Case 3: Full Visibility Specification
```json
{
  "input": {
    "name": "Test Article Full Visibility",
    "parent": {"itemId": "7986891993049776128"},
    "status": "PUBLISHED",
    "content": "<p>Test content with full visibility</p>",
    "visibility": {
      "added": [{
        "portalType": "TECHNICIAN",
        "clientSharedType": "AllClients",
        "siteSharedType": "AllSites",
        "userRoleSharedType": "AllRoles",
        "userSharedType": "AllUsers",
        "groupSharedType": "AllGroups"
      }]
    },
    "loginRequired": false
  }
}
```
**Error**: `Internal Server Error(s) while executing query`

### Test Case 4: Multiple Portal Types
```json
{
  "visibility": {
    "added": [
      {
        "portalType": "TECHNICIAN",
        "userSharedType": "AllUsers"
      },
      {
        "portalType": "REQUESTER",
        "userSharedType": "AllUsers"
      }
    ]
  }
}
```
**Error**: `Internal Server Error(s) while executing query`

## Attempted Debugging Steps

1. **Introspection Queries**: Successfully mapped all input types and their requirements
2. **Enum Value Verification**: Confirmed all enum values (TECHNICIAN, REQUESTER, AllUsers, etc.) are valid
3. **Account/Client Query Attempts**: Tried to query for account/client IDs but those queries are not available
4. **Minimal Field Testing**: Tested with only required fields
5. **Various Visibility Combinations**: Tested 10+ different visibility configurations

## Current Status

- ✅ Can parse ITGlue exports (673 documents ready)
- ✅ Can transform content to clean HTML
- ✅ Can create categories/collections via GraphQL
- ✅ Can list existing KB items
- ❌ Cannot create articles due to visibility field errors
- ❌ No clear documentation on visibility field requirements

## Questions for SuperOps Development Team

1. **What is the correct format for the visibility field when creating KB articles?**
   - Do we need specific account/client/site IDs?
   - Is there a "public" or "all access" configuration?
   - Can visibility be set after article creation?

2. **Are there alternative approaches?**
   - REST API endpoints for KB article creation?
   - Bulk import functionality?
   - Different permission model for API-created content?

3. **Is the internal server error related to:**
   - Missing tenant/account configuration?
   - API permissions/scopes?
   - Required fields not documented in the schema?

## Environment Details

- **Subdomain**: wyretechnology
- **Data Center**: US
- **API Token**: Valid and authenticated (categories work)
- **GraphQL Endpoint**: https://api.superops.ai/msp
- **Headers**: Authorization Bearer + CustomerSubDomain

## Test Scripts Included

1. `test_create_category.py` - Successful category creation
2. `test_create_article.py` - Failed article creation attempts
3. `test_visibility_types.py` - Enum value discovery
4. `test_minimal_article.py` - Minimal required fields test
5. `test_full_visibility.py` - Complete visibility specification test

## Migration Tool Overview

The complete migration tool includes:
- Batch processing with progress tracking
- Error recovery and retry logic
- State management for resume capability
- Content transformation and sanitization
- Attachment handling preparation
- Organization-based categorization

The tool is production-ready except for the article creation blocker.