#!/usr/bin/env python3
"""Introspect the getKbItem query structure."""

import asyncio
import os
import httpx
import json
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def introspect_kb_item():
    """Introspect the getKbItem query structure."""
    
    api_token = os.getenv("SUPEROPS_API_TOKEN")
    subdomain = os.getenv("SUPEROPS_SUBDOMAIN")
    
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
    print("Introspecting getKbItem query structure")
    print("="*60)
    
    # Get the query field details
    introspection_query = """
    query {
        __schema {
            queryType {
                fields {
                    name
                    description
                    args {
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
        }
    }
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.superops.ai/msp",
            headers=headers,
            json={"query": introspection_query},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"]:
                fields = data["data"]["__schema"]["queryType"]["fields"]
                
                # Find KB-related queries
                kb_queries = [f for f in fields if 'kb' in f['name'].lower()]
                
                print("\nKB-related queries found:")
                for query in kb_queries:
                    print(f"\n{query['name']}:")
                    print(f"  Description: {query.get('description', 'No description')}")
                    if query.get('args'):
                        print("  Arguments:")
                        for arg in query['args']:
                            arg_type = arg['type']
                            type_name = arg_type.get('name')
                            if not type_name and arg_type.get('ofType'):
                                type_name = arg_type['ofType'].get('name')
                            required = arg_type['kind'] == 'NON_NULL'
                            print(f"    - {arg['name']}: {type_name} {'(REQUIRED)' if required else '(optional)'}")
    
    # Now introspect the KbItem type
    print("\n" + "="*60)
    print("Introspecting KbItem type structure")
    print("="*60)
    
    type_query = """
    query {
        __type(name: "KbItem") {
            name
            kind
            fields {
                name
                description
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
            json={"query": type_query},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"] and data["data"]["__type"]:
                kb_type = data["data"]["__type"]
                print(f"\nType: {kb_type['name']} ({kb_type['kind']})")
                print("\nFields available:")
                
                for field in kb_type["fields"]:
                    field_type = field["type"]
                    type_name = field_type.get("name")
                    
                    if not type_name and field_type.get("ofType"):
                        type_name = field_type["ofType"].get("name")
                    
                    print(f"  - {field['name']}: {type_name}")
                    if field.get("description"):
                        print(f"    ({field['description']})")
    
    # Now introspect DocumentSharedDetails type
    print("\n" + "="*60)
    print("Introspecting DocumentSharedDetails type")
    print("="*60)
    
    visibility_query = """
    query {
        __type(name: "DocumentSharedDetails") {
            name
            kind
            fields {
                name
                description
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
            json={"query": visibility_query},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"] and data["data"]["__type"]:
                visibility_type = data["data"]["__type"]
                print(f"\nType: {visibility_type['name']} ({visibility_type['kind']})")
                print("\nFields available:")
                
                for field in visibility_type["fields"]:
                    field_type = field["type"]
                    type_name = field_type.get("name")
                    
                    if not type_name and field_type.get("ofType"):
                        type_name = field_type["ofType"].get("name")
                    
                    print(f"  - {field['name']}: {type_name}")
    
    # Try the correct getKbItem query
    print("\n" + "="*60)
    print("Testing correct getKbItem query")
    print("="*60)
    
    # Based on introspection, try the correct structure
    get_item_query = """
    query GetKbItem($input: GetKbItemInput!) {
        getKbItem(input: $input) {
            itemId
            name
            itemType
            description
            status
            visibility {
                clientSharedType
                siteSharedType
                userRoleSharedType
                userSharedType
                groupSharedType
                selectedAccountsList
                selectedRolesList
                selectedSitesList
                selectedUsersList
                selectedGroupsList
            }
            loginRequired
            parent {
                itemId
                name
            }
        }
    }
    """
    
    test_id = "8097544195105165312"  # General Documentation collection
    
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
                print("Errors:")
                print(json.dumps(data["errors"], indent=2))
            
            if "data" in data and data["data"]:
                item = data["data"].get("getKbItem")
                if item:
                    print("\n✅ Successfully retrieved item!")
                    print(json.dumps(item, indent=2))
                    
                    if item.get("visibility"):
                        print("\n" + "="*40)
                        print("VISIBILITY STRUCTURE:")
                        print("="*40)
                        print(json.dumps(item["visibility"], indent=2))

if __name__ == "__main__":
    asyncio.run(introspect_kb_item())