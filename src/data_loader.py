"""
Module untuk load dan parse file CSV tagihan
"""
import pandas as pd
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def parse_nominal(value: any) -> int:
    """
    Parse nominal dari format " 50,000 " menjadi 50000

    Args:
        value: Nilai nominal (string atau number)

    Returns:
        int: Nilai nominal dalam integer
    """
    if pd.isna(value) or value == '' or value is None:
        return 0
    
    # Remove all non-numeric characters (handles both dots and commas as separators)
    import re
    cleaned = re.sub(r'[^\d]', '', str(value))
    
    try:
        if not cleaned:
            return 0
        return int(cleaned)
    except ValueError:
        logger.warning(f"Gagal parse nominal: {value}")
        return 0


def is_paid(value: any) -> bool:
    """
    Cek apakah bulan sudah dibayar.
    - Ada nilai > 0 (tidak kosong/NaN/0) = True (SUDAH BAYAR)
    - Kosong/NaN/null/0/- = False (BELUM BAYAR)

    Args:
        value: Nilai kolom bulan

    Returns:
        bool: True jika sudah bayar, False jika belum
    """
    if pd.isna(value) or value == '' or value is None:
        return False
    
    val_str = str(value).strip()
    
    # Abaikan yang kosong atau cuma strip
    if not val_str or val_str == '-':
        return False
        
    # Cek apakah ini nol (misal 0, 0,0, Rp0, Rp 0)
    import re
    digits = re.sub(r'[^\d]', '', val_str)
    
    if digits:
        try:
            # Kalau ada angka, harus lebih dari 0
            if int(digits) == 0:
                return False
            return True
        except ValueError:
            pass
            
    # Jika tidak ada angka samasekali tapi ada isinya (misal "Lunas"), anggap sudah bayar
    return True


def get_month_columns(df: pd.DataFrame) -> list[str]:
    """
    Extract list kolom bulan dari dataframe.
    Kolom bulan adalah kolom setelah 'Nominal' yang formatnya XXX'YY

    Args:
        df: DataFrame yang sudah di-load

    Returns:
        list[str]: List nama kolom bulan
    """
    try:
        nominal_idx = df.columns.get_loc('Nominal')
        # Get semua kolom setelah Nominal
        month_cols = df.columns[nominal_idx + 1:].tolist()
        # Filter hanya yang match pattern bulan (ada tanda petik ')
        month_cols = [str(m) for m in month_cols if "'" in str(m)]
        return month_cols
    except ValueError:
        logger.warning("Kolom 'Nominal' tidak ditemukan")
        return []


def load_csv(file_path: str | Path) -> Optional[pd.DataFrame]:
    """
    Parse CSV dengan format khusus (Sama seperti sebelumnya)
    """
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File CSV tidak ditemukan: {file_path}")
            return None

        # 1. Temukan baris header secara dinamis (cari baris yang mengandung Nama dan Nominal)
        header_idx = 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    # Check for keywords in the line
                    if "Nama" in line and "Nominal" in line:
                        header_idx = i
                        break
        except Exception as e:
            logger.warning(f"Gagal deteksi header dinamis, gunakan default: {e}")

        # 2. Read with auto-detect separator
        # First try auto-detect, then fallback to common separators if it fails
        try:
            df = pd.read_csv(
                file_path,
                skiprows=header_idx,
                header=0,      
                sep=None,      
                engine='python',
                dtype=str,
                encoding='utf-8'
            )
        except:
            # Fallback to semicolon or comma if auto-detect fails
            df = pd.read_csv(
                file_path,
                skiprows=header_idx,
                header=0,
                sep=';',
                engine='python',
                dtype=str,
                encoding='utf-8'
            )

        # 3. CRITICAL: Strip whitespace dari semua nama kolom
        df.columns = df.columns.str.strip()

        # Rename 'No' to 'ID' for consistency if exists
        if 'No' in df.columns:
            df.rename(columns={'No': 'ID'}, inplace=True)

        # Remove baris dengan ID kosong
        if 'ID' in df.columns:
            df = df[df['ID'].notna() & (df['ID'].astype(str).str.strip() != '')]
            df = df[df['ID'].astype(str).str.strip() != 'TOTAL']
            df = df[df['ID'].astype(str).str.strip().str.isnumeric()]
        
        # Reset index
        df = df.reset_index(drop=True)

        # Ensure kolom Nama dan Nominal ada
        if 'Nama' not in df.columns or 'Nominal' not in df.columns:
            logger.error(f"Kolom wajib ('Nama'/'Nominal') tidak ditemukan. Kolom yang ada: {df.columns.tolist()}")
            return None

        # Clean nominal column dan tambah kolom Nominal_Clean
        df['Nominal_Clean'] = df['Nominal'].apply(parse_nominal)

        logger.info(f"Berhasil load {len(df)} baris data (Header at line {header_idx})")
        return df

    except Exception as e:
        logger.error(f"Error tidak terduga saat load CSV: {e}")
        return None

def load_master_data(file_path: str | Path) -> Optional[pd.DataFrame]:
    """Load master client database"""
    try:
        df = pd.read_csv(file_path, dtype=str, encoding='utf-8')
        df.columns = df.columns.str.strip()
        df['ID'] = df['ID'].astype(str).str.strip()
        return df
    except Exception as e:
        logger.error(f"Gagal load master data: {e}")
        return None

def load_billing_data(directory_path: str | Path) -> Dict[str, pd.DataFrame]:
    """Load all billing CSVs from a directory"""
    billing_dfs = {}
    path = Path(directory_path)
    if not path.exists():
        logger.warning(f"Directory billing {directory_path} tidak ditemukan")
        return billing_dfs

    for file in path.glob("*.csv"):
        village_name = file.stem.lower()
        df = load_csv(file)
        if df is not None:
            billing_dfs[village_name] = df
            logger.info(f"Loaded billing for {village_name}: {len(df)} rows")
    
    return billing_dfs


def normalize_name(name: str) -> str:
    """
    Normalize nama untuk pencarian case-insensitive

    Args:
        name: Nama yang akan di-normalize

    Returns:
        str: Nama dalam lowercase dan tanpa spasi berlebih
    """
    if pd.isna(name) or name is None:
        return ""
    return str(name).strip().lower()


if __name__ == "__main__":
    # Test fungsi
    logging.basicConfig(level=logging.DEBUG)
    df = load_csv("bahrulhuda.csv")
    if df is not None:
        print(f"Loaded {len(df)} rows")
        print(f"Columns: {df.columns.tolist()}")
        print(f"Month columns: {get_month_columns(df)}")
        print("\nSample data:")
        print(df[['No', 'Nama', 'Alamat', 'Nominal_Clean']].head())
