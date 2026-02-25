"""
Konfigurasi Telegram Bot Pembayaran Tagihan
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN tidak ditemukan! "
        "Buat file .env dengan isi: BOT_TOKEN=your_token_here"
    )

# Path Configuration
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MASTER_DATA_PATH = DATA_DIR / "master.csv"
BILLING_DATA_DIR = DATA_DIR / "billing"

# Bot Settings
BOT_USERNAME = "Pembayaran Tagihan Bot"

# Search Settings
FUZZY_THRESHOLD = 0.4        # Threshold untuk fuzzy matching nama
MAX_SEARCH_BUTTONS = 10      # Maksimal tombol pilihan warga yang muncul jika nama ganda

# File Watcher Settings
RELOAD_DELAY = float(os.getenv("RELOAD_DELAY", "1.0"))

# Display Settings
MAX_UNPAID_LIST = int(os.getenv("MAX_UNPAID_LIST", "100"))
MAX_PAID_LIST = int(os.getenv("MAX_PAID_LIST", "100"))

# UI & Formatting
CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "Rp")
CURRENCY_THOUSAND_SEP = os.getenv("CURRENCY_THOUSAND_SEP", ".")
CURRENCY_DECIMAL_SEP = os.getenv("CURRENCY_DECIMAL_SEP", ",")

# Data Structure & Columns
# Note: MONTH_COLUMNS and MONTH_NAME_MAP are now dynamically derived in data_manager.py

# Daftar Desa dan File-nya
VILLAGE_FILES = {
    'Putat': 'putat.csv',
    'Segaran': 'segaran.csv',
    'Gondang Legi': 'gondanglegi.csv'
}

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Admin Configuration
def _parse_admin_ids():
    import re
    raw_ids = os.getenv("ADMIN_IDS", "")
    parts = re.split(r'[;,\s]+', raw_ids)
    return [int(uid.strip()) for uid in parts if uid.strip().isdigit()]

ADMIN_IDS = _parse_admin_ids()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Batas Tanggal Pembayaran per Dusun/Desa
DUSUN_DEADLINE = {
    'putat': 15,
    'gondang legi': 5,
    'segaran': 15,
}

DEFAULT_DEADLINE = 15
