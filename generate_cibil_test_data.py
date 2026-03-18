import random
import string
from datetime import datetime, timedelta

MAIN_ROWS = 200000
IDENTITY_COVERAGE = 0.6  # 60% customers will have identity data

main_file = "main_data.txt"
identity_file = "identity_data.txt"


def random_date():
    start = datetime(2010, 1, 1)
    end = datetime(2025, 12, 31)
    delta = end - start
    return (start + timedelta(days=random.randint(0, delta.days))).strftime("%Y-%m-%d")


def random_pan():
    return (
        "".join(random.choices(string.ascii_uppercase, k=5))
        + "".join(random.choices(string.digits, k=4))
        + random.choice(string.ascii_uppercase)
    )


def random_passport():
    return random.choice(string.ascii_uppercase) + "".join(random.choices(string.digits, k=7))


def random_voter():
    return "".join(random.choices(string.ascii_uppercase, k=2)) + "".join(random.choices(string.digits, k=7))


def random_uid():
    return "".join(random.choices(string.digits, k=12))


def random_ration():
    return "RC" + "".join(random.choices(string.digits, k=10))


def random_dl():
    return "DL" + "".join(random.choices(string.digits, k=12))


def maybe(value, prob=0.7):
    """Return value or empty string randomly"""
    return value if random.random() < prob else ""


print("Generating main_data.txt ...")

customer_ids = []

with open(main_file, "w") as f:
    f.write("ACCT_KEY|CUSTOMER_ID|INCOME|INCOME_FREQ|OCCUP_STATUS_CD|RPT_DT|BANK_TYPE\n")

    for i in range(MAIN_ROWS):
        # Mix normal + phone-like IDs
        if random.random() < 0.2:
            customer_id = f"+91 {random.randint(7000000000, 9999999999)}"
        else:
            customer_id = str(random.randint(9000000000, 9999999999))

        customer_ids.append(customer_id)

        acct_key = random.randint(100000000, 9999999999)
        income = random.choice([random.randint(10000, 200000), ""])
        income_freq = random.choice(["1", "2", "3", "4", ""])
        occup = random.choice(["1", "5", "9", "10", "99"])
        rpt_dt = random_date()
        bank = random.choice(["PVT", "NBF", "HFC", "PSU"])

        f.write(f"{acct_key}|{customer_id}|{income}|{income_freq}|{occup}|{rpt_dt}|{bank}\n")

        if i % 50000 == 0 and i != 0:
            print(f"{i} main rows generated")

print("Main file complete.")


print("Generating identity_data.txt ...")

selected_ids = random.sample(customer_ids, int(len(customer_ids) * IDENTITY_COVERAGE))

with open(identity_file, "w") as f:
    f.write("CUSTOMER_ID|PAN|PASSPORT|VOTER_ID|UID|RATION_CARD|DRIVING_LICENSE\n")

    for i, customer_id in enumerate(selected_ids):
        pan = random_pan()
        passport = maybe(random_passport())
        voter = maybe(random_voter())
        uid = maybe(random_uid())
        ration = maybe(random_ration())
        dl = maybe(random_dl())

        f.write(f"{customer_id}|{pan}|{passport}|{voter}|{uid}|{ration}|{dl}\n")

        if i % 50000 == 0 and i != 0:
            print(f"{i} identity rows generated")

print("Identity file complete.")