from crypto_vault import (
    generate_vault,
    unlock_vault,
    VaultAuthenticationError,
)


# ============================================
# BASELINE VOICE
# ============================================

baseline_formants = [
    500, 750, 1000, 1250,
    1500, 1750, 2000, 2250,
    2500, 2750, 3000, 3250,
    3500, 3750, 4000, 4250,
    4500, 4750, 5000, 5250,
    5500, 5750, 6000, 6250,
    6500, 6750, 7000, 7250,
    7500, 7750, 8000, 8250,
    8500, 8750, 9000, 9250,
    9500, 9750, 10000, 10250,
]


# ============================================
# 1. GENERATE VAULT
# ============================================

print("\n[1] Generating vault...")

vault = generate_vault(
    baseline_formants
)

print("    Vault generated!")
print(
    f"    Points: {len(vault['points'])}"
)


# ============================================
# 2. AUTHENTICATE WITH EXACT SAME VOICE
# ============================================

print("\n[2] Testing exact voice...")

try:

    result = unlock_vault(
        baseline_formants,
        vault,
    )

    print("    AUTHENTICATION SUCCESS!")
    print(
        f"    Secret: {result.decode()}"
    )

except VaultAuthenticationError as exc:

    print("    AUTHENTICATION FAILED!")
    print(f"    Reason: {exc}")


# ============================================
# 3. TEST SLIGHT VOICE DRIFT
# ============================================

print("\n[3] Testing slightly different voice...")

drifted_formants = [
    512, 738, 1012, 1263,
    1511, 1762, 1987, 2248,
    2512, 2738, 3011, 3237,
    3512, 3738, 4012, 4237,
    4512, 4738, 5012, 5237,
    5512, 5738, 6012, 6237,
    6512, 6738, 7012, 7237,
    7512, 7738, 8012, 8237,
    8512, 8738, 9012, 9237,
    9512, 9738, 10012, 10237,
]


try:

    result = unlock_vault(
        drifted_formants,
        vault,
    )

    print("    DRIFT TEST SUCCESS!")
    print(
        f"    Secret: {result.decode()}"
    )

except VaultAuthenticationError as exc:

    print("    DRIFT TEST FAILED!")
    print(f"    Reason: {exc}")


# ============================================
# 4. TEST WRONG VOICE
# ============================================

print("\n[4] Testing completely different voice...")

wrong_formants = [
    300, 450, 600, 900,
    1100, 1350, 1600, 1850,
    2100, 2350, 2600, 2850,
    3100, 3350, 3600, 3850,
    4100, 4350, 4600, 4850,
    5100, 5350, 5600, 5850,
    6100, 6350, 6600, 6850,
    7100, 7350, 7600, 7850,
    8100, 8350, 8600, 8850,
    9100, 9350, 9600, 9850,
]


try:

    result = unlock_vault(
        wrong_formants,
        vault,
    )

    print("    WARNING: WRONG VOICE WAS ACCEPTED!")
    print(
        f"    Secret: {result.decode()}"
    )

except VaultAuthenticationError:

    print("    WRONG VOICE REJECTED!")
    print("    Authentication correctly failed.")


print("\n================================")
print("CHABI CRYPTO TEST COMPLETE")
print("================================")