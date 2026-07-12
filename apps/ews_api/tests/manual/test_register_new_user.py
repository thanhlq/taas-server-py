#!/usr/bin/env python3
"""
Test script for user registration endpoint

uv run python test_register_new_user.py
"""
import requests
import json
import random

# API Configuration
API_URL = "http://localhost:8191/api/v1/auth/signup"

# Test data
test_data: dict[str, str] = {
    "otp": "807689",
    "first_name": "Ngoc",
    "last_name": "Le",
    "email": "ngocle1401@gmail.com",
    "password": "Abcd@1234",
    "organization_name": "Ngoc Test Org " + str(random.randint(1, 9999)),
    "preferred_region": "US"
}

def test_register():
    print("=" * 80)
    print("Testing User Registration Endpoint")
    print("=" * 80)
    print(f"\n📍 API URL: {API_URL}")
    print(f"\n📋 Test Data:")
    print(json.dumps(test_data, indent=2))
    print("\n" + "=" * 80)

    try:
        print("\n🚀 Sending registration request...")
        response = requests.post(
            API_URL,
            json=test_data,
            headers={"Content-Type": "application/json"}
        )

        print(f"\n📊 Response Status: {response.status_code}")
        print(f"\n📄 Response Headers:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")

        print(f"\n📦 Response Body:")
        try:
            response_json = response.json()
            print(json.dumps(response_json, indent=2))

            # Check response
            if response.status_code == 200:
                print("\n✅ SUCCESS: User registration completed!")
                if response_json.get("data", {}).get("status") == "OK":
                    print("\n🎉 Registration successful!")
                    print(f"   - User ID: {response_json.get('data', {}).get('id')}")
                    print(f"   - Email: {test_data['email']}")
                    print(f"   - Organization: {test_data['organization_name']}")
                    print("\n📧 Check email verification:")
                    print(f"   - Email: {test_data['email']}")
                    print("   - Check your inbox for verification email")
                elif response_json.get("data", {}).get("status") == "EXISTED":
                    print("\n⚠️  User already exists!")
                    print(f"   - Email: {test_data['email']}")
                elif response_json.get("data", {}).get("status") == "FAILED":
                    print("\n❌ Registration failed!")
                    print(f"   - Message: {response_json.get('data', {}).get('message')}")
            else:
                print(f"\n❌ ERROR: Registration failed with status {response.status_code}")

        except json.JSONDecodeError:
            print(response.text)

    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to API server!")
        print(f"   - Make sure the server is running at {API_URL}")
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {str(e)}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_register()
