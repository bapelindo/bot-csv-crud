"""
Module untuk manage data tagihan dengan thread-safe reload dan async support
"""
import logging
import threading
import asyncio
import os
import tempfile
from datetime import datetime
from difflib import get_close_matches
from typing import Optional, List, Dict, Any
from pathlib import Path

import pandas as pd

from .data_loader import load_csv, is_paid, get_month_columns, normalize_name, parse_nominal
from .data_loader import load_master_data, load_billing_data

logger = logging.getLogger(__name__)


class BillDataManager:
    """
    Class untuk manage data pembayaran dengan Master/Detail architecture.
    Menangani Master Clients Join dengan Multiple Billing CSVs.
    """

    def __init__(self, master_path: str, billing_dir: str):
        self.master_path = master_path
        self.billing_dir = billing_dir
        self.df: pd.DataFrame = pd.DataFrame()
        self.lock = threading.RLock()
        self.month_columns: List[str] = []
        self.billing_dfs: Dict[str, pd.DataFrame] = {}
        self.file_watcher = None # For suppressing redundant reloads
        self._load_data()

    def set_file_watcher(self, watcher):
        """Link a file watcher for event suppression"""
        self.file_watcher = watcher

    def _load_data(self) -> bool:
        """Internal sync loading logic"""
        try:
            master_df = load_master_data(self.master_path)
            if master_df is None:
                logger.error("Failed to load master data")
                return False

            self.billing_dfs = load_billing_data(self.billing_dir)
            
            combined_billing = pd.DataFrame()
            for village, bdf in self.billing_dfs.items():
                bdf_copy = bdf.copy()
                bdf_copy['ID'] = bdf_copy['ID'].astype(str).str.strip()
                bdf_copy['Source_Village'] = village
                combined_billing = pd.concat([combined_billing, bdf_copy], ignore_index=True)

            if not combined_billing.empty:
                self.df = pd.merge(master_df, combined_billing, on='ID', how='left', suffixes=('', '_billing'))
                if 'Nama_billing' in self.df.columns:
                    self.df.drop(columns=['Nama_billing'], inplace=True)
                self.month_columns = get_month_columns(self.df)
            else:
                self.df = master_df
                self.month_columns = []

            logger.info(f"Data unified: {len(self.df)} rows, {len(self.month_columns)} months")
            return True
        except Exception as e:
            logger.error(f"Error loading and joining data: {e}", exc_info=True)
            return False

    async def load_data(self) -> bool:
        return await asyncio.to_thread(self.load_data_sync)

    def load_data_sync(self) -> bool:
        return self._sync_locked_call(self._load_data)

    async def reload_data(self) -> bool:
        logger.info("Reloading data (async)...")
        return await self.load_data()

    def reload_data_sync(self) -> bool:
        logger.info("Reloading data (sync)...")
        return self.load_data_sync()

    def _sync_locked_call(self, func, *args, **kwargs):
        with self.lock:
            return func(*args, **kwargs)

    async def get_available_months(self) -> List[str]:
        return await asyncio.to_thread(self._sync_locked_call, lambda: self.month_columns.copy())

    async def resolve_month(self, input_name: str) -> Optional[str]:
        return await asyncio.to_thread(self._sync_locked_call, self._resolve_month_sync, input_name)

    def _resolve_month_sync(self, input_name: str) -> Optional[str]:
        input_lower = input_name.strip().lower()
        available = self.month_columns
        if not available: return None
            
        for col in available:
            if col.lower() == input_lower: return col
                
        month_map = {
            'jan': 'JAN', 'januari': 'JAN', 'feb': 'FEB', 'februari': 'FEB',
            'mar': 'MAR', 'maret': 'MAR', 'apr': 'APR', 'april': 'APR',
            'mei': 'MEI', 'may': 'MEI', 'jun': 'JUN', 'juni': 'JUN',
            'jul': 'JUL', 'juli': 'JUL', 'agu': 'AGU', 'aug': 'AUG', 'agustus': 'AGU',
            'sep': 'SEP', 'september': 'SEP', 'okt': 'OKT', 'oct': 'OKT', 'oktober': 'OKT',
            'nov': 'NOV', 'november': 'NOV', 'des': 'DES', 'dec': 'DES', 'desember': 'DES'
        }
        
        target_abbr = month_map.get(input_lower)
        if target_abbr:
            now = datetime.now()
            current_yr = str(now.year)[-2:]
            variations = [target_abbr]
            if target_abbr == 'AGU': variations.append('AUG')
            if target_abbr == 'AUG': variations.append('AGU')
            if target_abbr == 'MEI': variations.append('MAY')
            if target_abbr == 'MAY': variations.append('MEI')
            
            for v in variations:
                p = f"{v}'{current_yr}"
                for col in available:
                    if col.upper() == p: return col
            
            matches = [c for c in available if c.split("'")[0].upper() in variations]
            if matches:
                matches.sort(key=lambda c: c.split("'")[1] if "'" in c else "00")
                return matches[-1]
        return None

    async def search_by_name(self, name: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sync_locked_call, self._search_by_name_sync, name)

    def _search_by_name_sync(self, name: str) -> List[Dict[str, Any]]:
        if self.df.empty: return []
        term = normalize_name(name)
        if not term: return []
        mask = self.df['Nama'].str.lower().str.contains(term, na=False, regex=False)
        res = self.df[mask].copy()
        if len(res) == 0:
            names = [normalize_name(n) for n in self.df['Nama'].tolist()]
            close = get_close_matches(term, names, n=5, cutoff=0.4)
            if close:
                res = self.df[self.df['Nama'].str.lower().isin(close)].copy()
        return self._format_results(res)

    async def get_payment_status(self, name: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._sync_locked_call, self._get_payment_status_sync, name)

    def _get_payment_status_sync(self, name: str) -> Optional[Dict[str, Any]]:
        results = self._search_by_name_sync(name)
        if not results: return None
        p = results[0]
        status = {
            'No': p.get('No', ''), 'Nama': p.get('Nama', ''), 'Alamat': p.get('Alamat', ''),
            'Nominal': p.get('Nominal_Clean', 0), 'Nominal_Original': p.get('Nominal', ''),
            'paid_months': [], 'unpaid_months': [], 'partial_months': [], 'payment_details': {}
        }
        for m in self.month_columns:
            val = p.get(m)
            paid = is_paid(val)
            amount = parse_nominal(val) if paid else 0
            status['payment_details'][m] = {'paid': paid, 'value': val if paid else None, 'amount': amount}
            if paid:
                status['paid_months'].append(m)
                if 0 < amount < status['Nominal']: status['partial_months'].append(m)
            else:
                status['unpaid_months'].append(m)
        return status

    async def get_unpaid_by_month(self, month: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sync_locked_call, self._get_unpaid_by_month_sync, month)

    def _get_unpaid_by_month_sync(self, month: str) -> List[Dict[str, Any]]:
        m_norm = month.upper().strip()
        if m_norm not in self.df.columns: return []
        mask = self.df[m_norm].isna() | (self.df[m_norm].astype(str).str.strip() == '')
        unpaid = self.df[mask & self.df['ID'].notna()].copy()
        return sorted(self._format_list_results(unpaid), key=lambda x: x['Nama'])

    async def get_paid_by_month(self, month: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sync_locked_call, self._get_paid_by_month_sync, month)

    def _get_paid_by_month_sync(self, month: str) -> List[Dict[str, Any]]:
        m_norm = month.upper().strip()
        if m_norm not in self.df.columns: return []
        mask = self.df[m_norm].apply(is_paid)
        paid = self.df[mask & self.df['ID'].notna()].copy()
        res = self._format_list_results(paid)
        for r, (_, row) in zip(res, paid.iterrows()): r['Value'] = str(row[m_norm])
        return sorted(res, key=lambda x: x['Nama'])

    def _format_list_results(self, df):
        return [{'No': str(r['ID']), 'Nama': str(r['Nama']), 'Alamat': str(r['Alamat']) if pd.notna(r['Alamat']) else '',
                 'Nominal': r['Nominal_Clean'] if 'Nominal_Clean' in r else 0,
                 'Nominal_Original': str(r['Nominal']) if 'Nominal' in r else ''} for _, r in df.iterrows()]

    async def update_payment(self, id_warga: str, month_column: str, value: Any, is_increment: bool = True) -> bool:
        return await asyncio.to_thread(self._sync_locked_call, self._update_payment_sync, id_warga, month_column, value, is_increment)

    def _update_payment_sync(self, id_warga: str, month_col: str, value: Any, is_increment: bool = True) -> bool:
        id_str = str(id_warga).strip()
        mask = self.df['ID'].astype(str).str.strip() == id_str
        if not mask.any(): return False
        resident = self.df[mask].iloc[0]
        village = str(resident.get('Source_Village', resident.get('Desa', ''))).lower().strip()
        v_file = Path(self.billing_dir) / f"{village}.csv"
        if not v_file.exists(): return False
        try:
            from .data_loader import load_csv
            v_df = load_csv(v_file)
            if v_df is None: return False
            v_mask = v_df['ID'].astype(str).str.strip() == id_str
            if not v_mask.any(): return False
            idx = v_df[v_mask].index[0]
            if is_increment:
                v_df.at[idx, month_col] = str(parse_nominal(v_df.at[idx, month_col]) + parse_nominal(value))
            else:
                v_df.at[idx, month_col] = str(parse_nominal(value))
            
            title_rows = []
            with open(v_file, 'r', encoding='utf-8') as f:
                for line in f:
                    title_rows.append(line)
                    if "Nama" in line and "Nominal" in line: break
            
            temp_fd, temp_path = tempfile.mkstemp(dir=v_file.parent, prefix=f"{village}_tmp_", suffix=".csv")
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8', newline='') as f:
                    for row in title_rows: f.write(row)
                    cols = [c for c in v_df.columns if c != 'Nominal_Clean']
                    save_df = v_df[cols].copy()
                    if "No" in title_rows[-1] and "ID" in save_df.columns: save_df.rename(columns={"ID": "No"}, inplace=True)
                    save_df.to_csv(f, index=False, lineterminator='\n')
                
                # Pause watcher before swap to avoid redundant reload
                if self.file_watcher: self.file_watcher.pause()
                
                os.replace(temp_path, v_file)
            except Exception as e:
                if os.path.exists(temp_path): os.remove(temp_path)
                raise e
            self._load_data()
            
            # Resume watcher after internal reload is complete
            if self.file_watcher: self.file_watcher.resume()
            
            return True
        except Exception as e:
            logger.error(f"Atomic update failed: {e}", exc_info=True)
            return False

    async def get_stats(self, target_month: Optional[str] = None) -> Dict[str, Any]:
        return await asyncio.to_thread(self.get_stats_sync, target_month)

    def get_stats_sync(self, target_month: Optional[str] = None) -> Dict[str, Any]:
        return self._sync_locked_call(self._get_stats_sync, target_month)

    def _get_stats_sync(self, target_month: Optional[str] = None) -> Dict[str, Any]:
        if self.df.empty: return {'total_warga': 0, 'total_bulan': 0}
        from .payment_checker import get_current_month_column
        cur_m = target_month or get_current_month_column(self.month_columns)
        stats = {'total_warga': len(self.df), 'total_bulan': len(self.month_columns), 'bulan_tersedia': self.month_columns,
                 'current_month': cur_m, 'current_month_paid_count': 0, 'current_month_collection': 0,
                 'current_month_total_expected': 0, 'village_breakdown': {}}
        if cur_m in self.df.columns:
            for _, row in self.df.iterrows():
                v = str(row.get('Desa', 'Lainnya'))
                if v not in stats['village_breakdown']: stats['village_breakdown'][v] = {'total': 0, 'paid': 0}
                stats['village_breakdown'][v]['total'] += 1
                stats['current_month_total_expected'] += parse_nominal(row.get('Nominal', 0))
                if is_paid(row.get(cur_m)):
                    amt = parse_nominal(row.get(cur_m))
                    stats['current_month_collection'] += amt
                    stats['current_month_paid_count'] += 1
                    stats['village_breakdown'][v]['paid'] += 1
        return stats

    def _format_results(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        res = []
        for _, row in df.iterrows():
            d = {}
            for c in df.columns:
                val = row[c]
                key = 'No' if c == 'ID' else c
                d[key] = str(val) if pd.notna(val) and c != 'Nominal_Clean' else (int(val) if pd.notna(val) else None)
            res.append(d)
        return res
