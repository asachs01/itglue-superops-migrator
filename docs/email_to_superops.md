# Email Draft: ITGlue to SuperOps KB Migration - Technical Assistance Needed

**To:** [VP of Sales], [Lead Tech]  
**Subject:** ITGlue to SuperOps Knowledge Base Migration - API Integration Issue

Hi [Names],

I hope this email finds you well. I'm making excellent progress on migrating our Knowledge Base from ITGlue to SuperOps, but I've encountered a technical blocker with the GraphQL API that we need your development team's assistance to resolve.

## Quick Summary

I've built an automated migration tool to transfer 673 Knowledge Base articles from ITGlue to SuperOps. The tool successfully:
- ✅ Authenticates with the API
- ✅ Creates categories/collections 
- ✅ Parses and transforms content
- ❌ **Fails when creating articles due to visibility field configuration**

## What I'm Trying to Accomplish

Our migration tool is designed to:
1. Parse ITGlue's HTML exports (673 documents across 35 organizational categories)
2. Transform and clean the content for SuperOps
3. Create the category structure in SuperOps KB
4. Upload articles with proper categorization and metadata
5. Track progress for resumable migrations

## The Technical Issue

The `createKbArticle` mutation requires a `visibility` field of type `CreateDocumentShareInput`. Every configuration I've tested returns an "Internal Server Error" from the API. Through GraphQL introspection, I've confirmed the field structure and tested with all valid enum values.

### Our Testing Methodology

**GraphQL Request Details:**
- Method: POST
- URL: `https://api.superops.ai/msp`
- Headers:
  ```
  Authorization: Bearer [API_TOKEN]
  CustomerSubDomain: wyretechnology
  Content-Type: application/json
  ```

**GraphQL Mutation:**
```graphql
mutation CreateKbArticle($input: CreateKbArticleInput!) {
    createKbArticle(input: $input) {
        itemId
        name
    }
}
```

### Configurations I've Tested

1. **With proper enum values (from introspection):**
```json
{
  "input": {
    "name": "Test Article",
    "content": "<p>Article content</p>",
    "parent": {"itemId": "8097544195105165312"},
    "status": "PUBLISHED",
    "loginRequired": false,
    "visibility": {
      "added": [{
        "portalType": "TECHNICIAN",
        "userSharedType": "AllUsers"
      }]
    }
  }
}
```
**Response:** `Internal Server Error(s) while executing query`

2. **Empty visibility array:**
```json
"visibility": {"added": []}
```
**Response:** `Internal Server Error(s) while executing query`

3. **Multiple portal types:**
```json
"visibility": {
  "added": [
    {"portalType": "REQUESTER", "clientSharedType": "AllClients"},
    {"portalType": "TECHNICIAN", "userSharedType": "AllUsers"}
  ]
}
```
**Response:** `Internal Server Error(s) while executing query`

### Schema Information (from introspection)

**CreateDocumentShareInput requires:**
- `added`: `[NewShareDetailsInput!]!` (NonNull array)

**NewShareDetailsInput fields:**
- `portalType`: RoleTypeEnum (TECHNICIAN | REQUESTER)
- `clientSharedType`: ClientSharedType (AllClients | Client)
- `userSharedType`: UserSharedType (AllUsers | User)
- `groupSharedType`: GroupSharedType (AllGroups | Group)
- Additional optional fields for specific IDs

**The paradox:** The field is required (NonNull) but any valid value causes an internal server error.

## What We Need

Could your development team provide:

1. **A working example** of the createKbArticle mutation with the correct visibility field format
2. **Clarification on required IDs** - Do we need specific account/client/site IDs for visibility?
3. **Alternative approaches** - Is there a REST API endpoint or bulk import option we should use instead?
4. **Confirmation if this is a known issue** - I've tested both `/msp` and `/it` endpoints with identical results

## Why This Matters

We have 673 critical documentation articles that our team relies on daily. Getting this migration completed will allow us to fully transition to SuperOps and decommission our ITGlue instance. The migration tool is 90% complete - we just need to solve this final hurdle.

## Technical Evidence

### Working Operations (Proving Authentication is Correct)

**Creating Collections (Categories) - WORKS:**
```graphql
mutation CreateKbCollection($input: CreateKbCollectionInput!) {
    createKbCollection(input: $input) {
        itemId
        name
    }
}
```
```json
{"input": {"name": "Test Collection"}}
```
**Result:** ✅ Successfully creates collections

**Listing KB Items - WORKS:**
```graphql
query GetKbItems($page: Int, $pageSize: Int) {
    getKbItems(listInfo: {page: $page, pageSize: $pageSize}) {
        items { itemId, name, itemType }
    }
}
```
**Result:** ✅ Successfully returns 6 collections

### Our Migration Tool Capabilities

Our migration tool is sophisticated and production-ready:
- Handles batch processing with progress tracking
- Includes retry logic and error recovery
- Maintains state for resumable migrations
- Transforms content with proper HTML sanitization
- Successfully parses 673 ITGlue documents
- Creates category structure in SuperOps
- **Only fails at the article creation step**

I'm committed to making this work and would greatly appreciate your team's guidance on the correct API usage.

Please let me know if you need any additional information or would like to schedule a technical call to discuss this further.

Best regards,  
[Your name]

---

**P.S.** - Environment details:
- Endpoints tested: `https://api.superops.ai/msp` and `https://api.superops.ai/it` (both fail identically)
- Subdomain: wyretechnology  
- Data Center: US
- API Token: Valid (proven by successful collection creation and queries)
- Testing performed: December 22, 2024
- Total test configurations attempted: 20+ variations of the visibility field