#!/usr/bin/env python3
"""Introspect enum values for visibility types."""

import asyncio
import os
import httpx
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def introspect_enums():
    """Introspect enum values."""
    
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
    
    # List of enums to introspect
    enums = [
        "RoleTypeEnum",
        "ClientSharedType", 
        "SiteSharedType",
        "UserRoleSharedType",
        "UserSharedType",
        "GroupSharedType",
        "ArticleStatus"
    ]
    
    for enum_name in enums:
        query = f"""
        query {{
            __type(name: "{enum_name}") {{
                name
                kind
                enumValues {{
                    name
                    description
                }}
            }}
        }}
        """
        
        print(f"\n{'='*50}")
        print(f"Introspecting {enum_name}")
        print('='*50)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.superops.ai/msp",
                headers=headers,
                json={"query": query},
                timeout=10,
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if "data" in data and data["data"] and data["data"]["__type"]:
                    type_info = data["data"]["__type"]
                    if type_info and type_info.get("enumValues"):
                        print(f"Type: {type_info['name']} ({type_info['kind']})")
                        print("Values:")
                        for value in type_info["enumValues"]:
                            print(f"  - {value['name']}")
                            if value.get("description"):
                                print(f"    ({value['description']})")
                    else:
                        print(f"No enum values found for {enum_name}")
                else:
                    print(f"Type {enum_name} not found")

if __name__ == "__main__":
    asyncio.run(introspect_enums())