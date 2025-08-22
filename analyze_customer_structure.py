#!/usr/bin/env python3
"""Analyze ITGlue export to identify customer/client organization structure."""

import os
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set

def analyze_document_structure(export_path: str = "export-2/documents") -> Dict:
    """Analyze the document folder structure to identify customers."""
    
    documents_path = Path(export_path)
    if not documents_path.exists():
        print(f"Error: Path {export_path} does not exist")
        return {}
    
    # Track customers and their document categories
    customer_structure = defaultdict(lambda: {
        "categories": set(),
        "document_count": 0,
        "sample_docs": []
    })
    
    # Track overall statistics
    total_docs = 0
    all_categories = set()
    
    # Walk through the directory structure
    for root, dirs, files in os.walk(documents_path):
        root_path = Path(root)
        
        # Skip the root directory itself
        if root_path == documents_path:
            continue
            
        # Get relative path from documents root
        rel_path = root_path.relative_to(documents_path)
        path_parts = rel_path.parts
        
        if not path_parts:
            continue
            
        # First level is usually the customer/organization or category
        customer_or_category = path_parts[0]
        
        # Second level (if exists) is usually the document category
        category = path_parts[1] if len(path_parts) > 1 else "Root"
        
        # Count HTML files
        html_files = [f for f in files if f.endswith('.html')]
        if html_files:
            customer_structure[customer_or_category]["categories"].add(category)
            customer_structure[customer_or_category]["document_count"] += len(html_files)
            
            # Add sample document names (first 3)
            for doc in html_files[:3]:
                if len(customer_structure[customer_or_category]["sample_docs"]) < 3:
                    doc_path = root_path / doc
                    customer_structure[customer_or_category]["sample_docs"].append({
                        "name": doc,
                        "path": str(doc_path.relative_to(documents_path)),
                        "category": category
                    })
            
            total_docs += len(html_files)
            all_categories.add(category)
    
    # Convert sets to lists for JSON serialization
    result = {
        "summary": {
            "total_documents": total_docs,
            "total_customers_or_categories": len(customer_structure),
            "all_categories": sorted(list(all_categories))
        },
        "structure": {}
    }
    
    for customer, data in customer_structure.items():
        result["structure"][customer] = {
            "categories": sorted(list(data["categories"])),
            "document_count": data["document_count"],
            "sample_docs": data["sample_docs"]
        }
    
    return result

def identify_customer_patterns(structure_data: Dict) -> Dict:
    """Identify patterns to distinguish customers from general categories."""
    
    patterns = {
        "likely_customers": [],
        "likely_categories": [],
        "uncertain": []
    }
    
    # Common category names that are not customer names
    category_keywords = [
        "Processes", "Documentation", "Templates", "Procedures",
        "Standard Operating", "Configs", "Configurations", "How-To",
        "Applications", "Contracts", "General", "Internal"
    ]
    
    for name, data in structure_data["structure"].items():
        # Check if name contains category keywords
        is_category = any(keyword.lower() in name.lower() for keyword in category_keywords)
        
        # Check if it has multiple subcategories (likely a customer)
        has_subcategories = len(data["categories"]) > 1 and "Root" not in data["categories"]
        
        # Check document count (customers often have many docs)
        has_many_docs = data["document_count"] > 5
        
        # Classification logic
        if not is_category and (has_subcategories or has_many_docs):
            patterns["likely_customers"].append({
                "name": name,
                "document_count": data["document_count"],
                "categories": data["categories"]
            })
        elif is_category and not has_subcategories:
            patterns["likely_categories"].append({
                "name": name,
                "document_count": data["document_count"],
                "categories": data["categories"]
            })
        else:
            patterns["uncertain"].append({
                "name": name,
                "document_count": data["document_count"],
                "categories": data["categories"],
                "reason": "Mixed signals" if is_category and has_subcategories else "Few documents"
            })
    
    return patterns

def create_staging_plan(structure_data: Dict, patterns: Dict) -> Dict:
    """Create a staging plan for organizing documents."""
    
    staging_plan = {
        "customer_collections": {},
        "general_collections": {},
        "requires_review": []
    }
    
    # Plan customer collections
    for customer in patterns["likely_customers"]:
        staging_plan["customer_collections"][customer["name"]] = {
            "superops_collection": customer["name"],  # Can be mapped differently
            "document_count": customer["document_count"],
            "subcategories": customer["categories"],
            "action": "create_customer_collection"
        }
    
    # Plan general collections
    for category in patterns["likely_categories"]:
        staging_plan["general_collections"][category["name"]] = {
            "superops_collection": "General Knowledge Base",
            "subcategory": category["name"],
            "document_count": category["document_count"],
            "action": "add_to_general"
        }
    
    # Items requiring review
    for item in patterns["uncertain"]:
        staging_plan["requires_review"].append({
            "name": item["name"],
            "document_count": item["document_count"],
            "reason": item.get("reason", "Unclear classification"),
            "suggested_action": "manual_review"
        })
    
    return staging_plan

def main():
    """Main analysis function."""
    
    print("="*60)
    print("ITGlue Document Structure Analysis")
    print("="*60)
    
    # Analyze structure
    print("\n1. Analyzing document structure...")
    structure = analyze_document_structure()
    
    if not structure:
        return
    
    print(f"   Found {structure['summary']['total_documents']} documents")
    print(f"   Organized in {structure['summary']['total_customers_or_categories']} top-level folders")
    
    # Identify patterns
    print("\n2. Identifying customer vs. category patterns...")
    patterns = identify_customer_patterns(structure)
    
    print(f"   Likely customers: {len(patterns['likely_customers'])}")
    print(f"   Likely categories: {len(patterns['likely_categories'])}")
    print(f"   Uncertain: {len(patterns['uncertain'])}")
    
    # Create staging plan
    print("\n3. Creating staging plan...")
    staging_plan = create_staging_plan(structure, patterns)
    
    # Display results
    print("\n" + "="*60)
    print("IDENTIFIED CUSTOMERS")
    print("="*60)
    
    if patterns["likely_customers"]:
        for customer in sorted(patterns["likely_customers"], key=lambda x: x["document_count"], reverse=True):
            print(f"\n• {customer['name']}")
            print(f"  Documents: {customer['document_count']}")
            print(f"  Categories: {', '.join(customer['categories'][:3])}")
            if len(customer['categories']) > 3:
                print(f"              ... and {len(customer['categories']) - 3} more")
    else:
        print("No customer-specific folders identified")
    
    print("\n" + "="*60)
    print("GENERAL CATEGORIES")
    print("="*60)
    
    if patterns["likely_categories"]:
        for category in sorted(patterns["likely_categories"], key=lambda x: x["document_count"], reverse=True):
            print(f"\n• {category['name']}")
            print(f"  Documents: {category['document_count']}")
    else:
        print("No general categories identified")
    
    if patterns["uncertain"]:
        print("\n" + "="*60)
        print("REQUIRES MANUAL REVIEW")
        print("="*60)
        
        for item in patterns["uncertain"]:
            print(f"\n• {item['name']}")
            print(f"  Documents: {item['document_count']}")
            print(f"  Reason: {item['reason']}")
    
    # Save analysis results
    print("\n" + "="*60)
    print("SAVING ANALYSIS RESULTS")
    print("="*60)
    
    # Save structure analysis
    with open("document_structure_analysis.json", "w") as f:
        json.dump(structure, f, indent=2)
    print("✓ Saved structure analysis to: document_structure_analysis.json")
    
    # Save patterns
    with open("customer_patterns.json", "w") as f:
        json.dump(patterns, f, indent=2)
    print("✓ Saved customer patterns to: customer_patterns.json")
    
    # Save staging plan
    with open("staging_plan.json", "w") as f:
        json.dump(staging_plan, f, indent=2)
    print("✓ Saved staging plan to: staging_plan.json")
    
    print("\n" + "="*60)
    print("RECOMMENDED NEXT STEPS")
    print("="*60)
    print("\n1. Review the staging_plan.json file")
    print("2. Update config.yaml with customer mappings")
    print("3. Run migration with --stage flag to preview")
    print("4. Adjust customer assignments as needed")
    print("5. Proceed with migration by customer")
    
    # Create sample config snippet
    print("\n" + "="*60)
    print("SAMPLE CONFIG.YAML SNIPPET")
    print("="*60)
    print("\ncustomer_mapping:")
    
    for customer in patterns["likely_customers"][:5]:  # Show first 5
        print(f'  "{customer["name"]}": "{customer["name"]}"')
    
    if len(patterns["likely_customers"]) > 5:
        print(f"  # ... and {len(patterns['likely_customers']) - 5} more customers")
    
    print("\n  # Default collection for general categories")
    print('  default_collection: "General Knowledge Base"')
    print('  create_customer_collections: true')
    print('  parent_collection: "Client Documentation"')

if __name__ == "__main__":
    main()