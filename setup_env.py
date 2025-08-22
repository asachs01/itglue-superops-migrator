#!/usr/bin/env python3
"""Helper script to set up the .env file for SuperOps migration."""

import os
from pathlib import Path

def setup_env():
    """Set up the .env file with required configuration."""
    
    env_file = Path(".env")
    
    # Read existing .env if it exists
    env_vars = {}
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value
    
    print("SuperOps Migration Tool - Environment Setup")
    print("=" * 50)
    
    # Check API token
    if "SUPEROPS_API_TOKEN" in env_vars:
        print("✓ API Token is already set")
    else:
        print("✗ API Token is not set")
        print("  Please add SUPEROPS_API_TOKEN to your .env file")
    
    # Check subdomain
    if "SUPEROPS__SUBDOMAIN" not in env_vars:
        print("\n✗ Subdomain is not set")
        print("\nTo complete setup, add the following to your .env file:")
        print("\n  SUPEROPS__SUBDOMAIN=your_subdomain")
        print("\nWhere 'your_subdomain' is the first part of your SuperOps URL.")
        print("For example:")
        print("  - If your SuperOps URL is: acme.superops.com")
        print("  - Set: SUPEROPS__SUBDOMAIN=acme")
        
        subdomain = input("\nEnter your SuperOps subdomain (or press Enter to skip): ").strip()
        if subdomain:
            env_vars["SUPEROPS__SUBDOMAIN"] = subdomain
            print(f"  Will set: SUPEROPS__SUBDOMAIN={subdomain}")
    else:
        print(f"✓ Subdomain is set: {env_vars['SUPEROPS__SUBDOMAIN']}")
    
    # Check data center
    if "SUPEROPS__DATA_CENTER" not in env_vars:
        print("\n✗ Data center is not set")
        data_center = input("Enter your data center (us/eu) [default: us]: ").strip().lower() or "us"
        if data_center in ["us", "eu"]:
            env_vars["SUPEROPS__DATA_CENTER"] = data_center
            print(f"  Will set: SUPEROPS__DATA_CENTER={data_center}")
        else:
            print("  Invalid data center. Using default: us")
            env_vars["SUPEROPS__DATA_CENTER"] = "us"
    else:
        print(f"✓ Data center is set: {env_vars['SUPEROPS__DATA_CENTER']}")
    
    # Write updated .env file
    if "SUPEROPS__SUBDOMAIN" in env_vars:
        with open(env_file, "w") as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
        print(f"\n✅ Configuration saved to {env_file}")
        print("\nYou can now run: python test_migration.py")
    else:
        print("\n⚠️  Subdomain is required. Please update your .env file manually.")
    
    # Show current .env contents
    print("\nCurrent .env file contents:")
    print("-" * 30)
    if env_file.exists():
        with open(env_file, "r") as f:
            contents = f.read()
            # Mask the API token for display
            for line in contents.split("\n"):
                if "SUPEROPS_API_TOKEN" in line:
                    print("SUPEROPS_API_TOKEN=***[MASKED]***")
                else:
                    print(line)
    print("-" * 30)

if __name__ == "__main__":
    setup_env()