"""
Run this once to derive your Polymarket API credentials from your wallet private key.

Usage:
    python derive_key.py

When prompted, paste your wallet private key (starts with 0x).
"""
import os

private_key = input("Paste your wallet private key (0x...): ").strip()

try:
    from py_clob_client_v2 import ClobClient
except ImportError:
    print("\nERROR: py-clob-client-v2 not installed. Run: pip install py-clob-client-v2")
    raise SystemExit(1)

print("\nConnecting to Polymarket CLOB...")
client = ClobClient(
    "https://clob.polymarket.com",
    key=private_key,
    chain_id=137,
)

print("Deriving API credentials...")
creds = client.create_or_derive_api_key()

print("\n=== YOUR API CREDENTIALS ===")
print(f"POLY_API_KEY={creds.api_key}")
print(f"POLY_API_SECRET={creds.api_secret}")
print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")
print("\nCopy these into your .env file.")
print("Do NOT share them with anyone.")
