#!/usr/bin/env python3
"""Introspect the NewShareDetailsInput type structure."""

import asyncio
import os
import httpx
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def introspect_visibility_type():
    """Introspect the visibility type structure."""
    
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
    
    # Query to introspect the CreateKbArticleInput type
    introspection_query = """
    query {
        __type(name: "CreateKbArticleInput") {
            name
            kind
            inputFields {
                name
                description
                type {
                    name
                    kind
                    ofType {
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
    """
    
    print("Introspecting CreateKbArticleInput type...")
    print("="*50)
    
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
                type_info = data["data"]["__type"]
                if type_info:
                    print(f"Type: {type_info['name']} ({type_info['kind']})")
                    print("\nFields:")
                    for field in type_info["inputFields"]:
                        field_type = field["type"]
                        type_name = field_type.get("name")
                        
                        # Handle nested type info
                        if not type_name and field_type.get("ofType"):
                            of_type = field_type["ofType"]
                            type_name = of_type.get("name")
                            if not type_name and of_type.get("ofType"):
                                type_name = of_type["ofType"].get("name")
                        
                        required = field_type["kind"] == "NON_NULL"
                        print(f"  - {field['name']}: {type_name} {'(REQUIRED)' if required else '(optional)'}")
                        if field.get("description"):
                            print(f"    Description: {field['description']}")
    
    # Now introspect CreateDocumentShareInput
    print("\n" + "="*50)
    print("Introspecting CreateDocumentShareInput type...")
    print("="*50)
    
    share_introspection = """
    query {
        __type(name: "CreateDocumentShareInput") {
            name
            kind
            inputFields {
                name
                description
                type {
                    name
                    kind
                    ofType {
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
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.superops.ai/msp",
            headers=headers,
            json={"query": share_introspection},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"]:
                type_info = data["data"]["__type"]
                if type_info:
                    print(f"Type: {type_info['name']} ({type_info['kind']})")
                    print("\nFields:")
                    for field in type_info["inputFields"]:
                        field_type = field["type"]
                        type_name = field_type.get("name")
                        
                        # Handle nested type info
                        if not type_name and field_type.get("ofType"):
                            of_type = field_type["ofType"]
                            type_name = of_type.get("name")
                            if not type_name and of_type.get("ofType"):
                                type_name = of_type["ofType"].get("name")
                        
                        required = field_type["kind"] == "NON_NULL"
                        print(f"  - {field['name']}: {type_name} {'(REQUIRED)' if required else '(optional)'}")
                        if field.get("description"):
                            print(f"    Description: {field['description']}")
    
    # Now introspect NewShareDetailsInput
    print("\n" + "="*50)
    print("Introspecting NewShareDetailsInput type...")
    print("="*50)
    
    details_introspection = """
    query {
        __type(name: "NewShareDetailsInput") {
            name
            kind
            inputFields {
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
            json={"query": details_introspection},
            timeout=10,
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if "data" in data and data["data"]:
                type_info = data["data"]["__type"]
                if type_info:
                    print(f"Type: {type_info['name']} ({type_info['kind']})")
                    print("\nFields:")
                    for field in type_info["inputFields"]:
                        field_type = field["type"]
                        type_name = field_type.get("name")
                        
                        # Handle nested type info
                        if not type_name and field_type.get("ofType"):
                            of_type = field_type["ofType"]
                            type_name = of_type.get("name")
                        
                        required = field_type["kind"] == "NON_NULL"
                        print(f"  - {field['name']}: {type_name} {'(REQUIRED)' if required else '(optional)'}")
                        if field.get("description"):
                            print(f"    Description: {field['description']}")

if __name__ == "__main__":
    asyncio.run(introspect_visibility_type())