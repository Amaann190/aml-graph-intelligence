"""Load the HI-Small transfers into one compact frame with integer account IDs."""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUTPUT = ROOT / "data" / "processed"
TRANSACTIONS = RAW / "HI-Small_Trans.csv"
ACCOUNTS = RAW / "HI-Small_accounts.csv"

COLUMNS = ["time", "from_bank", "from_account", "to_bank", "to_account", "received",
           "receiving_currency", "paid", "payment_currency", "format", "label"]
TEXT = ["time", "from_bank", "from_account", "to_bank", "to_account"]
CATEGORIES = ["receiving_currency", "payment_currency", "format"]


def prepare(raw: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Turn raw rows (named as COLUMNS) into the analysis frame.

    Accounts are "bank/account" strings mapped to integer codes. `source_row` is the
    line number in the original CSV, counting the header as line 1, so every alert
    can be traced back to the file. Returns the frame and the code -> account lookup.
    """
    payer = raw.from_bank + "/" + raw.from_account
    payee = raw.to_bank + "/" + raw.to_account
    codes, accounts = pd.factorize(pd.concat([payer, payee], ignore_index=True))
    n = len(raw)
    frame = pd.DataFrame({
        "source_row": np.arange(2, n + 2, dtype=np.int64),
        "time": raw.time.to_numpy(),
        "day": raw.time.str[:10].str.replace("/", "-").to_numpy(),
        "minute": ((pd.to_datetime(raw.time, format="%Y/%m/%d %H:%M") - pd.Timestamp(0))
                   // pd.Timedelta(minutes=1)).astype(np.int64).to_numpy(),
        "source": codes[:n].astype(np.int32),
        "target": codes[n:].astype(np.int32),
        "paid": raw.paid.astype(float).to_numpy(),
        "payment_currency": raw.payment_currency.astype("category").to_numpy(),
        "received": raw.received.astype(float).to_numpy(),
        "receiving_currency": raw.receiving_currency.astype("category").to_numpy(),
        "format": raw.format.astype("category").to_numpy(),
        "label": raw.label.astype(np.int8).to_numpy(),
    })
    return frame, np.asarray(accounts, dtype=object)


def load_transactions(path: Path = TRANSACTIONS) -> tuple[pd.DataFrame, np.ndarray]:
    dtypes = {name: str for name in TEXT} | {name: "category" for name in CATEGORIES}
    dtypes |= {"received": float, "paid": float, "label": np.int8}
    raw = pd.read_csv(path, header=0, names=COLUMNS, dtype=dtypes)
    return prepare(raw)


def entity_key(account: str) -> str:
    """The transfers file pads bank IDs with zeros ("0126") and the accounts file does not ("126")."""
    bank, number = account.split("/", 1)
    return f"{bank.lstrip('0') or '0'}/{number}"


def load_entities(path: Path = ACCOUNTS) -> dict[str, str]:
    """Map each "bank/account" key (see entity_key) to its entity name in the accounts file."""
    accounts = pd.read_csv(path, dtype=str, usecols=["Bank ID", "Account Number", "Entity Name"])
    keys = (accounts["Bank ID"] + "/" + accounts["Account Number"]).map(entity_key)
    return dict(zip(keys, accounts["Entity Name"]))


def entity_name(entities: dict, account: str) -> str:
    return entities.get(entity_key(account), "unknown")
