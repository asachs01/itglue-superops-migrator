# Sample API Calls

## WORKING: Create Category/Collection
```graphql
mutation CreateKbCollection($input: CreateKbCollectionInput!) {
    createKbCollection(input: $input) {
        itemId
        name
    }
}
```

Variables:
```json
{
  "input": {
    "name": "Test Category"
  }
}
```

Response: SUCCESS - Returns itemId

## FAILING: Create Article
```graphql
mutation CreateKbArticle($input: CreateKbArticleInput!) {
    createKbArticle(input: $input) {
        itemId
        name
    }
}
```

Variables (all variations fail):
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

Response: ERROR - Internal Server Error(s) while executing query
