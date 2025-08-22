#!/usr/bin/env python3
"""Retrieve and inspect existing KB articles to understand their structure."""

import asyncio
import os
import httpx
import json
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def retrieve_kb_articles():
    """Retrieve and inspect existing KB articles."""
    
    api_token = os.getenv("SUPEROPS_API_TOKEN")
    subdomain = os.getenv("SUPEROPS__SUBDOMAIN")
    
    if not api_token or not subdomain:
        print("Missing API token or subdomain")
        return
    
    # Create client
    headers = {
        "Authorization": f"Bearer {api_token}",
        "CustomerSubDomain": subdomain,
        "Content-Type": "application/json",
    }
    
    print("="*60)
    print("STEP 1: List all KB items to find articles")
    print("="*60)
    
    # First, get list of all KB items
    list_query = """
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
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.superops.ai/msp",
            headers=headers,
            json={
                "query": list_query,
                "variables": {"page": 1, "pageSize": 50}
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"]:
                items = data["data"]["getKbItems"]["items"]
                total = data["data"]["getKbItems"]["listInfo"]["totalCount"]
                
                print(f"Found {total} total KB items")
                print("\nItems breakdown:")
                
                collections = [i for i in items if i["itemType"] == "KB_COLLECTION"]
                articles = [i for i in items if i["itemType"] == "KB_ARTICLE"]
                
                print(f"  - Collections: {len(collections)}")
                print(f"  - Articles: {len(articles)}")
                
                if collections:
                    print("\nCollections found:")
                    for col in collections[:5]:
                        print(f"  - {col['name']} (ID: {col['itemId']})")
                
                if articles:
                    print("\nArticles found:")
                    for art in articles[:5]:
                        print(f"  - {art['name']} (ID: {art['itemId']})")
                else:
                    print("\n⚠️  No articles found in the system")
    
    # Now try to get detailed information about a specific item
    print("\n" + "="*60)
    print("STEP 2: Get detailed KB item information")
    print("="*60)
    
    # Query to get full details of a KB item
    detail_query = """
    query GetKbItem($itemId: ID!) {
        getKbItem(itemId: $itemId) {
            itemId
            name
            itemType
            description
            content
            status
            visibility {
                added {
                    portalType
                    clientSharedType
                    siteSharedType
                    userRoleSharedType
                    userSharedType
                    groupSharedType
                    accountId
                    siteId
                    addedRoleIds
                    addedUserIds
                    addedGroupIds
                }
                removed {
                    portalType
                    accountId
                    siteId
                    removedRoleIds
                    removedUserIds
                    removedGroupIds
                }
            }
            loginRequired
            parent {
                itemId
                name
            }
            createdBy {
                userId
                name
            }
            createdAt
            updatedAt
        }
    }
    """
    
    # Try to get details for the first collection we find
    if collections:
        test_item_id = collections[0]["itemId"]
        print(f"\nRetrieving details for: {collections[0]['name']}")
        print(f"Item ID: {test_item_id}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.superops.ai/msp",
                headers=headers,
                json={
                    "query": detail_query,
                    "variables": {"itemId": test_item_id}
                },
                timeout=10,
            )
            
            print(f"\nResponse status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                if "errors" in data:
                    print(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
                
                if "data" in data and data["data"]:
                    item = data["data"].get("getKbItem")
                    if item:
                        print("\nItem details retrieved successfully!")
                        print(json.dumps(item, indent=2))
                        
                        # Check visibility structure
                        if item.get("visibility"):
                            print("\n" + "="*60)
                            print("VISIBILITY STRUCTURE FOUND:")
                            print("="*60)
                            print(json.dumps(item["visibility"], indent=2))
                    else:
                        print("No item data returned")
    
    # Try alternative query structure
    print("\n" + "="*60)
    print("STEP 3: Try alternative query for KB articles")
    print("="*60)
    
    # Simpler query without nested fields
    simple_query = """
    query {
        getKbItems(listInfo: {page: 1, pageSize: 10}) {
            items {
                itemId
                name
                itemType
                status
                loginRequired
            }
        }
    }
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.superops.ai/msp",
            headers=headers,
            json={"query": simple_query},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            if "data" in data and data["data"]:
                items = data["data"]["getKbItems"]["items"]
                print(f"\nRetrieved {len(items)} items with basic fields")
                
                # Show any articles
                articles = [i for i in items if i.get("itemType") == "KB_ARTICLE"]
                if articles:
                    print("\nArticle details:")
                    for art in articles:
                        print(f"\n{art['name']}:")
                        print(f"  - ID: {art['itemId']}")
                        print(f"  - Status: {art.get('status', 'N/A')}")
                        print(f"  - Login Required: {art.get('loginRequired', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(retrieve_kb_articles())