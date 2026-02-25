"""
Module untuk format output pesan Telegram
"""
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


# Table formatting constants
TABLE_BOX_DOUBLE = {
    'tl': '┌', 'tr': '┐', 'bl': '└', 'br': '┘',
    'h': '─', 'v': '│', 'cross': '┼'
}

TABLE_BOX_SINGLE = {
    'tl': '┏', 'tr': '┓', 'bl': '┗', 'br': '┛',
    'h': '━', 'v': '┃', 'cross': '╋'
}


def format_currency(value: Any) -> str:
    """
    Format integer ke format mata uang (konfigurasi di config.py)
    """
    from config import CURRENCY_SYMBOL, CURRENCY_THOUSAND_SEP
    try:
        # Pengecekan tipe dan cast ke int
        if isinstance(value, str):
            value = float(value.replace('Rp', '').replace(',', '').strip())

        value = int(float(value))

        # Format dengan separator ribuan sesuai config
        formatted = f"{value:,}".replace(',', CURRENCY_THOUSAND_SEP)
        
        return f"{CURRENCY_SYMBOL} {formatted}"
    except (TypeError, ValueError):
        return f"{CURRENCY_SYMBOL} 0"


def escape_markdown(text: str) -> str:
    """
    Escapes characters that could break Telegram's Markdown parsing.
    """
    if not text:
        return ""
    # Characters that need escaping in standard Markdown
    chars_to_escape = ['_', '*', '`', '[']
    escaped_text = str(text)
    for char in chars_to_escape:
        escaped_text = escaped_text.replace(char, f"\\{char}")
    return escaped_text



def format_bill_status(status: Dict[str, Any], month_columns: List[str], deadline_info: Dict[str, Any] = None) -> str:
    """
    Format output untuk command /cek dalam bentuk tabel

    Args:
        status: Dict status pembayaran dari get_payment_status()
        month_columns: List kolom bulan yang tersedia
        deadline_info: Dict info deadline pembayaran (opsional)

    Returns:
        str: Pesan yang sudah diformat dalam tabel
    """
    from .payment_checker import get_current_month_column, get_previous_month_column

    if not status:
        return "❌ Data tidak ditemukan."

    # Header info
    lines = [
        "📋 *Tagihan*",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 *Nama:* {status['Nama']}",
        f"📍 *Alamat:* {status['Alamat']}" if status['Alamat'] else "",
        f"� *Nominal:* {format_currency(status['Nominal'])}/bulan",
        "",
    ]

    # Filter out empty lines
    lines = [line for line in lines if line]

    # Add deadline info if available
    if deadline_info:
        dusun = deadline_info.get('dusun', '-')
        deadline = deadline_info.get('deadline', '-')
        payment_status_text = deadline_info.get('payment_status', '')

        lines.append(f"🏘 *Dusun:* {dusun.title()}")
        lines.append(f"📅 *Deadline:* Tanggal {deadline} setiap bulan")
        lines.append(f"🚦 *Status:* {payment_status_text}")
        lines.append("")

    # Create table for payment status
    lines.append("📊 *Status Pembayaran:*")
    lines.append(format_payment_table(status, month_columns, deadline_info))

    # Get current month with robust matching
    current_month = get_current_month_column(month_columns)

    paid_months = status['paid_months']
    unpaid_months = status['unpaid_months']
    nominal_wajib = status['Nominal']

    # Count types of payments
    count_full = 0
    count_partial = 0
    total_paid_nominal = 0

    for month in paid_months:
        amount = status['payment_details'][month].get('amount', 0)
        total_paid_nominal += amount
        if amount >= nominal_wajib:
            count_full += 1
        elif amount > 0:
            count_partial += 1
        else:
            # is_paid returned true but parsed nominal is 0? 
            # Treat as full if it's not a numeric value (e.g. "LUNAS")
            count_full += 1

    # Total unpaid (Hanya yang SUDAH JATUH TEMPO / s.d bulan ini)
    try:
        current_idx = month_columns.index(current_month)
        due_months = month_columns[:current_idx + 1]
    except ValueError:
        due_months = month_columns

    count_unpaid = len([m for m in unpaid_months if m in due_months])
    total_tagihan = count_unpaid * nominal_wajib

    lines.append("")
    lines.append("📌 *Ringkasan:*")
    lines.append(f"   ✓ {count_full} bulan lunas")
    if count_partial > 0:
        lines.append(f"   ⚠️ {count_partial} bulan kurang bayar")
    lines.append(f"   ✗ {count_unpaid} bulan belum bayar ({format_currency(total_tagihan)})")
    lines.append(f"   💰 Total terbayar: {format_currency(total_paid_nominal)}")

    return "\n".join(lines)


def format_payment_table(status: Dict[str, Any], month_columns: List[str], deadline_info: Dict[str, Any] = None) -> str:
    """
    Format status pembayaran dalam bentuk tabel grid yang rapi

    Args:
        status: Dict status pembayaran
        month_columns: List kolom bulan yang tersedia
        deadline_info: Dict info deadline pembayaran (opsional)

    Returns:
        str: Tabel dalam format text/monospace
    """
    from .payment_checker import get_current_month_column

    paid_set = set(status['paid_months'])
    unpaid_set = set(status['unpaid_months'])

    # Get current month with robust matching
    current_month = get_current_month_column(month_columns)

    # Group months into rows (3 months per row optimized for mobile)
    months_per_row = 3
    col_width = 8
    table_lines = []

    for i in range(0, len(month_columns), months_per_row):
        row_months = month_columns[i:i + months_per_row]
        
        # Border strings
        top_border = "┌"
        month_row = "│"
        sep_row = "├"
        status_row = "│"
        bottom_border = "└"

        for idx, month in enumerate(row_months):
            import re
            short_month = re.sub(r"'\d{2}", "", month)
            
            # Status emoji
            if month in paid_set:
                amount = status['payment_details'][month].get('amount', 0)
                nominal = status.get('Nominal', 0)
                
                if amount > 0 and amount < nominal:
                    status_emoji = "⚠️🌙" if month == current_month else "  ⚠️  "
                else:
                    status_emoji = "✅🌙" if month == current_month else "  ✅  "
            else:
                status_emoji = "❌🌙" if month == current_month else "  ❌  "

            # Build row parts
            top_border += "─" * col_width + ("┬" if idx < len(row_months) - 1 else "┐")
            month_row += f"{short_month:^{col_width}}│"
            sep_row += "─" * col_width + ("┼" if idx < len(row_months) - 1 else "┤")
            status_row += f"{status_emoji:^{col_width}}│"
            bottom_border += "─" * col_width + ("┴" if idx < len(row_months) - 1 else "┘")

        # Combine rows
        if i == 0:
            table_lines.append(top_border)
        table_lines.append(month_row)
        table_lines.append(sep_row)
        table_lines.append(status_row)
        
        if i + months_per_row < len(month_columns):
            # Mid-table row separator (T-join)
            mid_sep = "├"
            for j in range(len(row_months)):
                mid_sep += "─" * col_width + ("┼" if j < len(row_months) - 1 else "┤")
            table_lines.append(mid_sep)
        else:
            table_lines.append(bottom_border)

    # Legend
    table_lines.append("")
    table_lines.append("💡 Keterangan: 🌙 = Bulan ini  ✅ = Sudah bayar  ❌ = Belum bayar")

    # Use monospace preformatted text
    result = "```\n" + "\n".join(table_lines) + "\n```"
    return result


def format_unpaid_list(chunk: List[Dict[str, Any]], month: str, total_people: int, total_nominal: int, start_idx: int, part: int, total_parts: int) -> str:
    """
    Format output untuk command /tagihan dalam bentuk tabel tersplit
    """
    if not chunk and part == 1:
        return f"✅ Semua orang sudah membayar untuk bulan *{month}*!"

    lines = [
        f"📊 *Belum Bayar - {month}* (Bagian {part}/{total_parts})",
        f"👥 *Total:* {total_people} orang",
        "",
    ]

    # Create table
    table = format_unpaid_table(chunk, start_idx=start_idx)
    lines.append(table)

    # Total nominal
    if part == total_parts:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💵 *Total Tertunda:* {format_currency(total_nominal)}")

    return "\n".join(lines)


def get_short_address(alamat: str) -> str:
    alamat_lower = str(alamat).lower()
    if 'putat' in alamat_lower: return 'PUT'
    if 'segaran' in alamat_lower: return 'SGR'
    if 'gondang' in alamat_lower: return 'GDL'
    return str(alamat)[:3].upper()

def format_unpaid_table(people: List[Dict[str, Any]], start_idx: int = 1) -> str:
    """
    Format list orang yang belum bayar dalam bentuk tabel grid

    Args:
        people: List orang
        start_idx: Indeks awal

    Returns:
        str: Tabel dalam format monospace
    """
    if not people:
        return "```Tidak ada data```"

    for p in people:
        p['_alamat_sm'] = get_short_address(p.get('Alamat', '-'))

    max_no = max(2, len(str(start_idx + len(people) - 1)))
    max_nama = max(4, max(len(p['Nama']) for p in people))
    max_alamat = max(6, max(len(p['_alamat_sm']) for p in people))
    max_nominal = max(7, max(len(format_currency(p['Nominal'])) for p in people))

    padding = 2
    total_width = max_no + max_nama + max_alamat + max_nominal + (padding * 6)

    lines = []
    lines.append("┌" + "─" * (total_width - 2) + "┐")

    header = (
        "│ " +
        f"{'No':^{max_no}}" + " │ " +
        f"{'Nama':^{max_nama}}" + " │ " +
        f"{'Alamat':^{max_alamat}}" + " │ " +
        f"{'Nominal':^{max_nominal}}" + " │"
    )
    lines.append(header)

    sep = (
        "│ " +
        "─" * max_no + " ┼ " +
        "─" * max_nama + " ┼ " +
        "─" * max_alamat + " ┼ " +
        "─" * max_nominal + " │"
    )
    lines.append(sep)

    for i, person in enumerate(people, start_idx):
        # Escape markdown characters to prevent Telegram parse errors inside the table
        nama_raw = escape_markdown(person['Nama'])
        nama = nama_raw[:max_nama]
        alamat = person['_alamat_sm'][:max_alamat]
        nominal = format_currency(person['Nominal'])

        row = (
            "│ " +
            f"{i:^{max_no}}" + " │ " +
            f"{nama:<{max_nama}}" + " │ " +
            f"{alamat:<{max_alamat}}" + " │ " +
            f"{nominal:>{max_nominal}}" + " │"
        )
        lines.append(row)

    lines.append("└" + "─" * (total_width - 2) + "┘")
    return "```\n" + "\n".join(lines) + "\n```"


def format_paid_list(chunk: List[Dict[str, Any]], month: str, total_people: int, total_nominal: int, start_idx: int, part: int, total_parts: int) -> str:
    """
    Format output untuk list warga yang sudah bayar dalam bentuk tabel
    """
    if not chunk and part == 1:
        return f"😕 Belum ada data orang yang membayar untuk bulan *{month}*."

    lines = [
        f"✅ *Sudah Bayar - {month}* (Bagian {part}/{total_parts})",
        f"👥 *Total:* {total_people} orang",
        "",
    ]

    # Create table
    table = format_paid_table(chunk, start_idx=start_idx)
    lines.append(table)

    # Total nominal
    if part == total_parts:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💵 *Total Terbayar:* {format_currency(total_nominal)}")

    return "\n".join(lines)


def format_paid_table(people: List[Dict[str, Any]], start_idx: int = 1) -> str:
    """
    Format list orang yang sudah bayar dalam bentuk tabel grid
    """
    if not people:
        return "```Tidak ada data```"

    for p in people:
        p['_alamat_sm'] = get_short_address(p.get('Alamat', '-'))

    max_no = max(2, len(str(start_idx + len(people) - 1)))
    max_nama = max(4, max(len(p['Nama']) for p in people))
    max_alamat = max(6, max(len(p['_alamat_sm']) for p in people))
    max_nominal = max(7, max(len(format_currency(p['Nominal'])) for p in people))

    padding = 2
    total_width = max_no + max_nama + max_alamat + max_nominal + (padding * 6)

    lines = []
    lines.append("┌" + "─" * (total_width - 2) + "┐")

    header = (
        "│ " +
        f"{'No':^{max_no}}" + " │ " +
        f"{'Nama':^{max_nama}}" + " │ " +
        f"{'Alamat':^{max_alamat}}" + " │ " +
        f"{'Nominal':^{max_nominal}}" + " │"
    )
    lines.append(header)

    sep = (
        "│ " +
        "─" * max_no + " ┼ " +
        "─" * max_nama + " ┼ " +
        "─" * max_alamat + " ┼ " +
        "─" * max_nominal + " │"
    )
    lines.append(sep)

    for i, person in enumerate(people, start_idx):
        # Escape markdown characters to prevent Telegram parse errors inside the table
        nama_raw = escape_markdown(person['Nama'])
        nama = nama_raw[:max_nama]
        alamat = person['_alamat_sm'][:max_alamat]
        nominal = format_currency(person['Nominal'])

        row = (
            "│ " +
            f"{i:^{max_no}}" + " │ " +
            f"{nama:<{max_nama}}" + " │ " +
            f"{alamat:<{max_alamat}}" + " │ " +
            f"{nominal:>{max_nominal}}" + " │"
        )
        lines.append(row)

    lines.append("└" + "─" * (total_width - 2) + "┘")
    return "```\n" + "\n".join(lines) + "\n```"


def format_multiple_results(results: List[Dict[str, Any]], search_term: str) -> str:
    """
    Format output ketika pencarian menghasilkan multiple results

    Args:
        results: List hasil pencarian
        search_term: Kata kunci pencarian

    Returns:
        str: Pesan yang sudah diformat
    """
    if not results:
        return f"❌ Tidak ditemukan data dengan nama '*{search_term}*'.\n\n💡 Coba gunakan nama lengkap atau nama lain."

    if len(results) == 1:
        return f"✅ Ditemukan: *{results[0]['Nama']}*"

    lines = [
        f"🔍 Ditemukan *{len(results)}* orang dengan nama '*{search_term}*':",
        "",
    ]

    for i, person in enumerate(results, 1):
        nama = person['Nama']
        alamat = f" - {person['Alamat']}" if person.get('Alamat') else ""
        lines.append(f"{i}. {nama}{alamat}")

    lines.append("")
    lines.append("💡 Ketik nama lengkap untuk melihat detail.")

    return "\n".join(lines)


def format_client_list(chunk: List[Dict[str, Any]], start_idx: int, total_clients: int, part: int, total_parts: int) -> str:
    """
    Format output untuk daftar client dari master data per pesan agar tidak terpotong.
    
    Args:
        chunk: List data client untuk pesan ini
        start_idx: Indeks awal untuk nomor urut
        total_clients: Total semua warga
        part: Pesan urutan ke berapa
        total_parts: Jumlah total pesan yang akan dikirim
    """
    if not chunk:
        return "❌ Data client kosong atau belum diload."

    lines = [
        f"👥 *Daftar Semua Client (Bagian {part}/{total_parts})*",
        f"📊 *Total:* {total_clients} warga",
        "━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for i, person in enumerate(chunk, start_idx):
        nama = escape_markdown(person['Nama'])
        # Gunakan get_short_address misal ada
        alamat = get_short_address(person.get('Alamat', '-'))
        nominal = format_currency(person.get('Nominal', 0))
        lines.append(f"`{i:>3}.` *{nama}* ({alamat})\n   💶 {nominal}")

    return "\n".join(lines)


def format_help_message(available_months: List[str]) -> str:
    """
    Format pesan bantuan

    Args:
        available_months: List bulan yang tersedia

    Returns:
        str: Pesan bantuan
    """
    lines = [
        "🤖 *Bot Pembayaran Tagihan*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📌 *Perintah yang tersedia:*",
        "",
        "➖➖➖➖➖➖➖➖➖➖➖➖",
        "",
        "1. `/cek <nama>`",
        "   Cek status pembayaran seseorang",
        "   Contoh: `/cek Samiren`",
        "",
        "2. `/tagihan [bulan]`",
        "   Lihat siapa saja yang belum bayar",
        "   Contoh: `/tagihan` atau `/tagihan jan`",
        "",
        "3. `/start`",
        "   Menampilkan pesan bantuan ini",
        "",
        "➖➖➖➖➖➖➖➖➖➖➖➖",
        "",
        "💡 *Tips:*",
        "• Ketik nama langsung tanpa `/cek` juga bisa!",
        "• Pencarian tidak case-sensitive",
        "• Gunakan nama lengkap untuk hasil lebih akurat",
        "",
    ]

    if available_months:
        lines.append("*Bulan yang tersedia:*")
        month_abbr = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
                       'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
        # Tampilkan bulan dalam format yang rapi
        for i in range(0, len(month_abbr), 6):
            line = "  ".join(month_abbr[i:i+6])
            lines.append(f"   {line}")

    return "\n".join(lines)


def format_error_message(error_type: str, detail: str = "") -> str:
    """
    Format pesan error

    Args:
        error_type: Tipe error
        detail: Detail error

    Returns:
        str: Pesan error yang sudah diformat
    """
    error_messages = {
        'not_found': "❌ Data tidak ditemukan.",
        'invalid_month': "❌ Bulan tidak valid.",
        'no_argument': "❌ Format salah. Mohon berikan argumen.",
        'file_error': "❌ Error membaca data.",
        'unknown': "❌ Terjadi kesalahan.",
    }

    base_message = error_messages.get(error_type, error_messages['unknown'])
    if detail:
        return f"{base_message}\n\n{detail}"
    return base_message


def format_stats_message(stats: Dict[str, Any]) -> str:
    """
    Format pesan statistik dengan info progress yang detail
    """
    # General Info
    lines = [
        "📊 *Statistik Data*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"👥 Total Warga: *{stats['total_warga']}* orang",
        f"📅 Total Bulan: *{stats['total_bulan']}* bulan",
    ]

    # Current Month Progress
    if stats.get('current_month'):
        cur_mo = stats['current_month']
        paid_count = stats['current_month_paid_count']
        total_warga = stats['total_warga']
        percent = (paid_count / total_warga * 100) if total_warga > 0 else 0
        
        # Progress bar
        bar_len = 10
        filled = int(percent / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        
        from .payment_checker import format_month_column_to_indonesian
        month_name = format_month_column_to_indonesian(cur_mo)
        
        lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🏠 *Progres {month_name}*",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"💰 Terkumpul: *Rp {stats['current_month_collection']:,}*".replace(",", "."),
            f"📈 Persentase: *{percent:.1f}%*  [{bar}]",
            f"👥 Lunas: *{paid_count}* dari *{total_warga}* warga",
            "",
            "📍 *Detail per Desa:*",
        ])
        
        # Sort villages by name
        villages = sorted(stats['village_breakdown'].keys())
        for village in villages:
            vdata = stats['village_breakdown'][village]
            vp = (vdata['paid'] / vdata['total'] * 100) if vdata['total'] > 0 else 0
            lines.append(f"• {village}: *{vdata['paid']}/{vdata['total']}* ({vp:.0f}%)")

    # Footer hint
    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 _Klik tombol di bawah untuk detail per bulan_",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    # Test
    print(format_currency(50000))
    print(format_currency(100000))

    # Test unpaid list
    dummy_people = [
        {'Nama': 'Samiren', 'Alamat': 'Putat', 'Nominal': 50000},
        {'Nama': 'Idris', 'Alamat': 'Putat', 'Nominal': 100000},
    ]
    print(format_unpaid_list(dummy_people, "JAN'26"))
