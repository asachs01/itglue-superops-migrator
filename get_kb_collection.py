#!/usr/bin/env python3
"""Get a KB collection to see its visibility structure."""

import asyncio
import os
import httpx
import json
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def get_kb_collection():
    """Get a KB collection to see its structure."""
    
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
    print("Getting KB Collection Details")
    print("="*60)
    
    # First introspect KBItemIdentifierInput
    introspect_query = """
    query {
        __type(name: "KBItemIdentifierInput") {
            name
            kind
            inputFields {
                name
                type {
                    name
                    kind
                    ofType {
                        name
                        kind
                    }
                }
            }
        }
    }
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.superops.ai/msp",
            headers=headers,
            json={"query": introspect_query},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            if "data" in data and data["data"] and data["data"]["__type"]:
                input_type = data["data"]["__type"]
                print(f"\nInput type: {input_type['name']}")
                print("Fields:")
                for field in input_type.get("inputFields", []):
                    field_type = field["type"]
                    type_name = field_type.get("name")
                    if not type_name and field_type.get("ofType"):
                        type_name = field_type["ofType"].get("name")
                    required = field_type["kind"] == "NON_NULL"
                    print(f"  - {field['name']}: {type_name} {'(REQUIRED)' if required else ''}")
    
    # Now get the collection with correct input structure
    get_item_query = """
    query GetKbItem($input: KBItemIdentifierInput!) {
        getKbItem(input: $input) {
            itemId
            name
            itemType
            description
            status
            visibility {
                mappingId
                portalType
                clientSharedType
                siteSharedType
                userRoleSharedType
                client
                site
                roles
                userSharedType
                groupSharedType
                users
                groups
            }
            loginRequired
            parent {
                itemId
                name
            }
            createdBy
            createdOn
            lastModifiedBy
            lastModifiedOn
        }
    }
    """
    
    test_id = "8097544195105165312"  # General Documentation collection
    print(f"\nRetrieving collection: {test_id}")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.superops.ai/msp",
            headers=headers,
            json={
                "query": get_item_query,
                "variables": {
                    "input": {"itemId": test_id}
                }
            },
            timeout=10,
        )
        
        print(f"\nResponse status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if "errors" in data:
                print("\nErrors:")
                print(json.dumps(data["errors"], indent=2))
            
            if "data" in data and data["data"]:
                item = data["data"].get("getKbItem")
                if item:
                    print("\n✅ Successfully retrieved collection!")
                    print("\nFull item structure:")
                    print(json.dumps(item, indent=2))
                    
                    if item.get("visibility"):
                        print("\n" + "="*40)
                        print("VISIBILITY STRUCTURE FOR COLLECTION:")
                        print("="*40)
                        print(json.dumps(item["visibility"], indent=2))
                        
                        # Analyze the visibility
                        vis = item["visibility"]
                        print("\nVisibility Analysis:")
                        print(f"  - Portal Type: {vis.get('portalType', 'Not set')}")
                        print(f"  - Client Shared Type: {vis.get('clientSharedType', 'Not set')}")
                        print(f"  - User Shared Type: {vis.get('userSharedType', 'Not set')}")
                        print(f"  - Group Shared Type: {vis.get('groupSharedType', 'Not set')}")
                        
                        return vis
                else:
                    print("\nNo item returned")
    
    return None

if __name__ == "__main__":
    asyncio.run(get_kb_collection())