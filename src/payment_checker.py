"""
Module untuk mengecek status pembayaran berdasarkan tanggal dan lokasi
"""
from datetime import datetime
from typing import Dict, Any, List, Tuple
import logging

from config import DUSUN_DEADLINE, DEFAULT_DEADLINE

logger = logging.getLogger(__name__)


def get_dusun_from_alamat(alamat: str) -> str:
    """
    Extract nama dusun dari alamat

    Args:
        alamat: String alamat

    Returns:
        str: Nama dusun dalam lowercase
    """
    if not alamat:
        return ""

    alamat_lower = alamat.lower().strip()

    # Cek apakah ada nama dusun di alamat
    for dusun in DUSUN_DEADLINE.keys():
        if dusun in alamat_lower:
            return dusun

    return ""


def get_deadline_for_dusun(dusun: str) -> int:
    """
    Get tanggal deadline untuk dusun tertentu

    Args:
        dusun: Nama dusun

    Returns:
        int: Tanggal deadline (1-31)
    """
    dusun_lower = dusun.lower()
    return DUSUN_DEADLINE.get(dusun_lower, DEFAULT_DEADLINE)


def get_current_month_column(available_columns: List[str] = None) -> str:
    """
    Get nama kolom bulan saat ini, dengan fallback untuk variasi nama kolom.

    Args:
        available_columns: List kolom yang tersedia di CSV

    Returns:
        str: Nama kolom bulan (format: MMM'YY atau variasi yang ada)
    """
    now = datetime.now()
    month_abbreviations = {
        1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
        7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OKT', 11: 'NOV', 12: 'DES'
    }

    month_abbr = month_abbreviations[now.month]
    year_suffix = str(now.year)[-2:]  # 2 digit terakhir tahun

    if available_columns:
        return find_matching_month_column(month_abbr, year_suffix, available_columns)

    return f"{month_abbr}'{year_suffix}"


def get_current_month_name() -> str:
    """
    Get nama bulan saat ini dalam bahasa Indonesia

    Returns:
        str: Nama bulan (format: Januari, Februari, dll)
    """
    now = datetime.now()
    month_names = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April', 5: 'Mei', 6: 'Juni',
        7: 'Juli', 8: 'Agustus', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }

    return month_names[now.month]


def format_month_column_to_indonesian(month_column: str) -> str:
    """
    Convert format kolom bulan ke nama bulan Indonesia

    Args:
        month_column: Format MMM'YY (e.g., "JAN'26")

    Returns:
        str: Nama bulan Indonesia (e.g., "Januari 2026")
    """
    month_map = {
        'JAN': 'Januari', 'FEB': 'Februari', 'MAR': 'Maret', 'APR': 'April',
        'MEI': 'Mei', 'JUN': 'Juni', 'JUL': 'Juli', 'AGU': 'Agustus',
        'SEP': 'September', 'OKT': 'Oktober', 'NOV': 'November', 'DES': 'Desember'
    }

    # Extract month abbreviation
    for abbr, name in month_map.items():
        if abbr in month_column.upper():
            # Extract year robustly
            if "'" in month_column:
                year_suffix = month_column.split("'")[1]
                if year_suffix.isdigit():
                    year = f"20{year_suffix}"
                else:
                    year = year_suffix
            else:
                year = "2026" # fallback
            
            return f"{name} {year}"

    return month_column


def get_previous_month_column(available_columns: List[str] = None) -> str:
    """
    Get nama kolom bulan sebelumnya, dengan fallback untuk variasi nama kolom.

    Args:
        available_columns: List kolom yang tersedia di CSV

    Returns:
        str: Nama kolom bulan sebelumnya (format: MMM'YY atau variasi yang ada)
    """
    now = datetime.now()

    # Hitung bulan sebelumnya
    if now.month == 1:
        prev_month = 12
        prev_year = now.year - 1
    else:
        prev_month = now.month - 1
        prev_year = now.year

    month_abbreviations = {
        1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MEI', 6: 'JUN',
        7: 'JUL', 8: 'AGU', 9: 'SEP', 10: 'OKT', 11: 'NOV', 12: 'DES'
    }

    month_abbr = month_abbreviations[prev_month]
    year_suffix = str(prev_year)[-2:]

    if available_columns:
        return find_matching_month_column(month_abbr, year_suffix, available_columns)

    return f"{month_abbr}'{year_suffix}"


def find_matching_month_column(month_abbr: str, year_suffix: str, available_columns: List[str]) -> str:
    """
    Cari kolom yang paling cocok dengan mempertimbangkan variasi singkatan.
    E.g. SEP vs SEPT, AGU vs AUG.

    Args:
        month_abbr: Singkatan standar (JAN, FEB, ...)
        year_suffix: 2 digit tahun (26, 27, ...)
        available_columns: List kolom di CSV

    Returns:
        str: Kolom yang ditemukan atau format standar jika tidak ada.
    """
    # Variasi umum
    variations = {
        'AGU': ['AGU', 'AUG'],
        'SEP': ['SEP', 'SEPT'],
        'MEI': ['MEI', 'MAY'],
    }

    targets = variations.get(month_abbr, [month_abbr])
    standard_pattern = f"{month_abbr}'{year_suffix}"

    # Cek setiap variasi
    for t in targets:
        pattern = f"{t}'{year_suffix}"
        if pattern in available_columns:
            return pattern

    # Jika tidak ketemu, return standar
    return standard_pattern


def is_payment_overdue(deadline: int, current_month_paid: bool) -> bool:
    """
    Cek apakah pembayaran sudah overdue/telat

    Args:
        deadline: Tanggal deadline pembayaran
        current_month_paid: Status pembayaran bulan ini

    Returns:
        bool: True jika sudah overdue (lewat deadline dan belum bayar)
    """
    if current_month_paid:
        return False

    now = datetime.now()
    today = now.day

    # Jika hari ini sudah lewat deadline, dianggap overdue
    return today > deadline


def get_payment_status_info(person: Dict[str, Any], month_columns: List[str]) -> Dict[str, Any]:
    """
    Get informasi status pembayaran dengan logika deadline

    Args:
        person: Dict data orang
        month_columns: List kolom bulan yang tersedia

    Returns:
        Dict: Informasi status pembayaran lengkap dengan deadline
    """
    from .data_loader import is_paid

    alamat = person.get('Alamat', '')
    dusun = get_dusun_from_alamat(alamat)
    deadline = get_deadline_for_dusun(dusun) if dusun else DEFAULT_DEADLINE

    current_month = get_current_month_column(month_columns)
    previous_month = get_previous_month_column(month_columns)

    # Cek status pembayaran
    current_month_paid = is_paid(person.get(current_month))
    previous_month_paid = is_paid(person.get(previous_month))

    # Cek overdue
    overdue = is_payment_overdue(deadline, current_month_paid)

    return {
        'dusun': dusun or '-',
        'deadline': deadline,
        'current_month': current_month,
        'previous_month': previous_month,
        'current_month_paid': current_month_paid,
        'previous_month_paid': previous_month_paid,
        'overdue': overdue,
        'payment_status': get_payment_status_text(current_month_paid, overdue, deadline)
    }


def get_payment_status_text(paid: bool, overdue: bool, deadline: int) -> str:
    """
    Get text status pembayaran

    Args:
        paid: Sudah bayar atau belum
        overdue: Sudah overdue atau belum
        deadline: Tanggal deadline

    Returns:
        str: Text status
    """
    now = datetime.now()

    if paid:
        return f"✅ Sudah bayar bulan ini"
    elif overdue:
        return f"🔴 BELUM BAYAR - Sudah lewat tgl {deadline}"
    else:
        days_until_deadline = deadline - now.day
        if days_until_deadline == 0:
            return f"🟡 Deadline HARI INI (tgl {deadline})"
        elif days_until_deadline == 1:
            return f"🟡 Deadline BESOK (tgl {deadline})"
        elif days_until_deadline < 0:
            return f"🔴 BELUM BAYAR - Lewat {abs(days_until_deadline)} hari"
        else:
            return f"🟢 Belum bayar - Masih {days_until_deadline} hari lagi"


def get_current_period_info() -> Dict[str, str]:
    """
    Get informasi periode pembayaran saat ini

    Returns:
        Dict: Informasi periode
    """
    now = datetime.now()
    month_names = {
        1: 'Januari', 2: 'Februari', 3: 'Maret', 4: 'April', 5: 'Mei', 6: 'Juni',
        7: 'Juli', 8: 'Agustus', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Desember'
    }

    return {
        'current_month_name': month_names[now.month],
        'current_year': now.year,
        'current_date': now.strftime('%d/%m/%Y'),
        'current_day': now.day
    }
