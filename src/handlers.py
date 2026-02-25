"""
Telegram Bot Command Handlers
"""
import logging
import asyncio
from typing import Optional

from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ForceReply
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from .data_manager import BillDataManager
from .payment_checker import get_payment_status_info, get_current_month_column, get_current_month_name, format_month_column_to_indonesian
from config import is_admin, MAX_UNPAID_LIST, MAX_PAID_LIST, MAX_SEARCH_BUTTONS
from .formatters import (
    format_bill_status,
    format_unpaid_list,
    format_paid_list,
    format_help_message,
    format_error_message,
    format_stats_message,
    format_currency,
    format_client_list
)
from .data_loader import parse_nominal
from telegram.ext import ConversationHandler

logger = logging.getLogger(__name__)

# State constants for ConversationHandler
WAITING_AMOUNT = 1


class BotHandlers:
    """
    Class yang berisi semua command handlers untuk Telegram Bot
    """

    def __init__(self, data_manager: BillDataManager):
        """
        Initialize BotHandlers

        Args:
            data_manager: Instance dari BillDataManager
        """
        self.data_manager = data_manager

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /start

        Menampilkan pesan selamat datang dan bantuan.
        """
        try:
            available_months = await self.data_manager.get_available_months()

            message = (
                "👋 *Selamat Datang di Bot Pembayaran Tagihan!*\n\n"
                "Bot ini membantu Anda mengecek status pembayaran tagihan warga.\n\n"
                "📱 *Pengguna Smartphone:* Silakan klik tombol menu di bawah ini untuk kemudahan akses."
            )

            # Create Keyboard
            keyboard = [
                [KeyboardButton("🔍 Cek Tagihan"), KeyboardButton("📅 Belum Bayar")],
                [KeyboardButton("✅ Paid"), KeyboardButton("📊 Statistik")],
                [KeyboardButton("👥 Daftar Client")],
                [KeyboardButton("❓ Bantuan")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

            if update.effective_message:
                await update.effective_message.reply_text(
                    message, 
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )

        except Exception as e:
            logger.error(f"Error di start_command: {e}")
            message_obj = update.effective_message
            if message_obj:
                await message_obj.reply_text(
                    "❌ Terjadi kesalahan. Silakan coba lagi."
                )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /help

        Menampilkan pesan bantuan.
        """
        await self.start_command(update, context)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /stats [bulan]
        """
        try:
            target_month = None
            if context.args and len(context.args) > 0:
                bulan_input = " ".join(context.args).strip().lower()
                target_month = await self.data_manager.resolve_month(bulan_input)
                
                if not target_month:
                    if update.effective_message:
                        await update.effective_message.reply_text(
                        f"❌ Bulan '*{bulan_input}*' tidak ditemukan.\n"
                        f"Gunakan `/stats` untuk bulan ini atau klik tombol indikator.",
                        parse_mode='Markdown'
                    )
                    return

            stats = await self.data_manager.get_stats(target_month)
            message = format_stats_message(stats)
            
            # Create interactive buttons for months
            keyboard = []
            available_months = stats.get('bulan_tersedia', [])
            
            # Arrange in 4 columns grid
            row = []
            for i, month in enumerate(available_months):
                row.append(InlineKeyboardButton(month, callback_data=f"st_mo_{month}"))
                if len(row) == 4:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
                
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            if update.effective_message:
                await update.effective_message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error di stats_command: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Terjadi kesalahan saat mengambil statistik."
            )

    async def _show_multiple_results_keyboard(self, update: Update, search_results: List[Dict[str, Any]]):
        """
        Tampilkan hasil pencarian yang banyak menggunakan inline keyboard bertahap (chunking).
        """
        chunk_size = 20 # Batasi jumlah tombol per pesan agar tidak terlalu panjang
        total_parts = (len(search_results) + chunk_size - 1) // chunk_size

        tasks = []
        for part, i in enumerate(range(0, len(search_results), chunk_size), 1):
            chunk = search_results[i:i + chunk_size]
            keyboard = []
            
            for person in chunk:
                label = f"{person['Nama']}"
                if person.get('Alamat'):
                    label += f" ({person['Alamat']})"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"view_res_{person['No']}")])
            
            text = f"🔎 *Ditemukan {len(search_results)} warga*"
            if total_parts > 1:
                text += f" (Bagian {part}/{total_parts})"
            text += ", silakan pilih:"

            if update.effective_message:
                tasks.append(update.effective_message.reply_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                ))
                
        if tasks:
            await asyncio.gather(*tasks)

    async def cek_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /cek <nama>

        Mengecek status pembayaran seseorang berdasarkan nama.
        """
        try:
            # Parse argument
            if not context.args or len(context.args) == 0:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "❌ Format salah. Gunakan: `/stats [bulan]`\n"
                        "Atau klik tombol indikator bulan.",
                        parse_mode='Markdown'
                    )
                return

            # Join all args as search term (for names with spaces)
            search_term = " ".join(context.args).strip()

            if not search_term:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "❌ Nama tidak boleh kosong.",
                        parse_mode='Markdown'
                    )
                return

            logger.info(f"Searching for: {search_term}")

            # Cek apakah ada multiple results
            search_results = await self.data_manager.search_by_name(search_term)

            if not search_results:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        format_error_message('not_found', f"Data dengan nama '*{search_term}*' tidak ditemukan."),
                        parse_mode='Markdown'
                    )
                return

            # Jika multiple results, tampilkan list dulu chunked
            if len(search_results) > 1:
                await self._show_multiple_results_keyboard(update, search_results)
                return

            # Single result
            await self._show_resident_detail(update, search_results[0])

        except Exception as e:
            logger.error(f"Error di cek_command: {e}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan saat mencari data."
                )

    async def cek_text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk pesan teks biasa (bukan command).

        Perlakukan sama seperti /cek command.
        """
        try:
            # Get text message
            text = update.effective_message.text if update.effective_message else ""

            if not text or not text.strip():
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "👋 Hai! Ketik nama untuk mengecek status pembayaran,\n"
                        "atau ketik /help untuk bantuan."
                    )
                return

            search_term = text.strip()

            # Legacy ForceReply handling removed - now using ConversationHandler

            chat_type = update.effective_chat.type
            is_group = chat_type in ['group', 'supergroup']
            
            # Khusus di Grup: Hanya respon jika di-mention atau reply ke bot
            if is_group:
                bot_username = context.bot.username
                mention = f"@{bot_username}"
                is_mentioned = bot_username and mention in text
                reply_to_message = update.effective_message.reply_to_message if update.effective_message else None
                is_reply_to_bot = reply_to_message and reply_to_message.from_user.id == context.bot.id
                
                # Jika tidak di-mention dan bukan reply ke bot, abaikan (biar gak berisik)
                if not is_mentioned and not is_reply_to_bot:
                    return
                
                # Jika di-mention, hapus mentionnya dari search_term biar pencarian bersih
                if is_mentioned:
                    search_term = text.replace(mention, "").strip()

            # Handle menu button clicks
            if search_term == "🔍 Cek Tagihan":
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "🔍 *Pencarian Tagihan*\n\n"
                        "Silakan ketik nama warga yang ingin Anda cek status pembayarannya.\n"
                        "Contoh: `Samiren` atau `Hartini`",
                        parse_mode='Markdown'
                    )
                return
            elif search_term == "📅 Belum Bayar":
                # Redirect to tagihan command (uses current month by default)
                await self.tagihan_command(update, context)
                return
            elif search_term == "✅ Paid":
                # Redirect to paid command
                await self.paid_command(update, context)
                return
            elif search_term == "📊 Statistik":
                # Redirect to stats command
                await self.stats_command(update, context)
                return
            elif search_term == "👥 Daftar Client":
                # Redirect to client list command
                await self.client_list_command(update, context)
                return
            elif search_term == "❓ Bantuan":
                available_months = await self.data_manager.get_available_months()
                message = format_help_message(available_months)
                if update.effective_message:
                    await update.effective_message.reply_text(message, parse_mode='Markdown')
                return

            logger.info(f"Text search for: {search_term}")

            # Cek apakah ada multiple results
            search_results = await self.data_manager.search_by_name(search_term)

            if not search_results:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        format_error_message('not_found', f"Data dengan nama '*{search_term}*' tidak ditemukan.\n\n💡 Ketik /help untuk bantuan."),
                        parse_mode='Markdown'
                    )
                return

            # Jika multiple results, tampilkan list dulu chunked
            if len(search_results) > 1:
                await self._show_multiple_results_keyboard(update, search_results)
                return

            # Single result
            await self._show_resident_detail(update, search_results[0])

        except Exception as e:
            logger.error(f"Error di cek_text_handler: {e}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan saat mencari data."
                )

    async def tagihan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /tagihan [bulan]

        Menampilkan daftar orang yang belum membayar.
        - /tagihan → bulan ini
        - /tagihan januari → bulan januari (dll)
        """
        try:
            # Parse argument
            if context.args and len(context.args) > 0:
                bulan_input = " ".join(context.args).strip().lower()
                month_column = await self.data_manager.resolve_month(bulan_input)

                if not month_column:
                    if update.effective_message:
                        await update.effective_message.reply_text(
                            f"❌ Bulan '*{bulan_input}*' tidak ditemukan dalam data.\n\n"
                            f"*Contoh:*\n"
                            f"• `/tagihan` (bulan ini)\n"
                            f"• `/tagihan jan` atau `/tagihan jan'26`\n"
                            f"• `/tagihan februari`",
                            parse_mode='Markdown'
                        )
                    return

                month_display = format_month_column_to_indonesian(month_column)

            else:
                # Tidak ada argumen, gunakan bulan ini
                available_columns = await self.data_manager.get_available_months()
                month_column = get_current_month_column(available_columns)
                month_display = get_current_month_name()

            logger.info(f"Checking unpaid for: {month_column}")

            # Get unpaid list
            unpaid_list = await self.data_manager.get_unpaid_by_month(month_column)

            if not unpaid_list:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        f"✅ *Semua warga sudah bayar* untuk bulan *{month_display}*.",
                        parse_mode='Markdown'
                    )
                return

            chunk_size = 50
            total_parts = (len(unpaid_list) + chunk_size - 1) // chunk_size
            total_nominal = sum(person['Nominal'] for person in unpaid_list)

            # Send chunks concurrently to avoid UX lag
            tasks = []
            for part, i in enumerate(range(0, len(unpaid_list), chunk_size), 1):
                chunk = unpaid_list[i:i + chunk_size]
                message = format_unpaid_list(
                    chunk=chunk,
                    month=month_display,
                    total_people=len(unpaid_list),
                    total_nominal=total_nominal,
                    start_idx=i + 1,
                    part=part,
                    total_parts=total_parts
                )

                if update.effective_message:
                    # Append coroutine instead of awaited result
                    tasks.append(update.effective_message.reply_text(message, parse_mode='Markdown'))
                    
            if tasks:
                await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Error di tagihan_command: {e}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan saat mengambil data tagihan."
                )

    async def paid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /paid [bulan]

        Menampilkan daftar orang yang sudah membayar.
        """
        try:
            # Parse argument
            available_columns = await self.data_manager.get_available_months()
            month_column = None
            month_display = None

            if context.args and len(context.args) > 0:
                bulan_input = " ".join(context.args).strip().lower()
                month_column = await self.data_manager.resolve_month(bulan_input)
                
                if month_column:
                    month_display = format_month_column_to_indonesian(month_column)
            
            if not month_column:
                month_column = get_current_month_column(available_columns)
                month_display = get_current_month_name()

            logger.info(f"Checking paid for: {month_column}")

            # Get paid list
            paid_list = await self.data_manager.get_paid_by_month(month_column)

            if not paid_list:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        f"😕 Belum ada data orang yang membayar untuk bulan *{month_display}*.",
                        parse_mode='Markdown'
                    )
                return

            chunk_size = 50
            total_parts = (len(paid_list) + chunk_size - 1) // chunk_size
            total_nominal = sum(person['Nominal'] for person in paid_list)

            tasks = []
            for part, i in enumerate(range(0, len(paid_list), chunk_size), 1):
                chunk = paid_list[i:i + chunk_size]
                message = format_paid_list(
                    chunk=chunk,
                    month=month_display,
                    total_people=len(paid_list),
                    total_nominal=total_nominal,
                    start_idx=i + 1,
                    part=part,
                    total_parts=total_parts
                )

                if update.effective_message:
                    tasks.append(update.effective_message.reply_text(message, parse_mode='Markdown'))
                    
            if tasks:
                await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Error di paid_command: {e}", exc_info=True)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan saat mengambil data pembayaran."
                )

    async def client_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /clients (Daftar Client)
        Menampilkan master data semua klien.
        """
        try:
            logger.info("Melihat daftar semua client")
            clients = await self.data_manager.get_all_clients()
            
            if not clients:
                if update.effective_message:
                    await update.effective_message.reply_text("❌ Data client kosong atau belum diload.")
                return

            chunk_size = 50
            total_parts = (len(clients) + chunk_size - 1) // chunk_size
            
            tasks = []
            for part, i in enumerate(range(0, len(clients), chunk_size), 1):
                chunk = clients[i:i + chunk_size]
                message = format_client_list(
                    chunk=chunk,
                    start_idx=i + 1,
                    total_clients=len(clients),
                    part=part,
                    total_parts=total_parts
                )
                
                if update.effective_message:
                    tasks.append(update.effective_message.reply_text(message, parse_mode='Markdown'))
                    
            if tasks:
                await asyncio.gather(*tasks)
                
        except Exception as e:
            logger.error(f"Error di client_list_command: {e}", exc_info=True)
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan saat mengambil data client."
                )

    async def reload_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /reload

        Manual reload data CSV.
        """
        try:
            if update.effective_message:
                await update.effective_message.reply_text("🔄 Me-reload data...")

            success = await self.data_manager.reload_data()

            if success:
                stats = await self.data_manager.get_stats()
                if update.effective_message:
                    await update.effective_message.reply_text(
                        f"✅ Data berhasil di-reload!\n\n"
                        f"📊 Total: {stats['total_warga']} warga, "
                        f"{stats['total_bulan']} bulan."
                    )
            else:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "❌ Gagal me-reload data. Cek log untuk detail."
                    )

        except Exception as e:
            logger.error(f"Error di reload_command: {e}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan saat me-reload data."
                )

    async def bayar_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /bayar [nama]
        """
        user_id = update.effective_user.id
        is_user_admin = is_admin(user_id)
        logger.info(f"Command /bayar by {user_id}, admin: {is_user_admin}")
        
        if not is_user_admin:
            if update.effective_message:
                await update.effective_message.reply_text("⛔ *Maaf, hanya Admin yang bisa mengakses fitur ini.*", parse_mode='Markdown')
            return

        query = " ".join(context.args) if context.args else ""
        if not query:
            if update.effective_message:
                await update.effective_message.reply_text("💡 *Contoh penggunaan:* `/bayar Samiren`", parse_mode='Markdown')
            return

        results = await self.data_manager.search_by_name(query)

        if not results:
            if update.effective_message:
                await update.effective_message.reply_text(f"❌ Warga dengan nama *{query}* tidak ditemukan.", parse_mode='Markdown')
            return

        if len(results) > 1:
            keyboard = []
            for person in results[:8]:
                keyboard.append([InlineKeyboardButton(f"{person['Nama']} ({person['Alamat']})", callback_data=f"pay_sel_{person['No']}")])
            
            if update.effective_message:
                await update.effective_message.reply_text(
                    "🔍 *Hasil Pencarian*\n\n"
                    "Gunakan tombol di bawah untuk melihat detail atau rekam pembayaran.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            return

        await self._show_pay_months(update, results[0])

    async def _show_pay_months(self, update_or_query, person):
        no_warga = person.get('No')
        nama = person.get('Nama')
        
        status = await self.data_manager.get_payment_status(nama)
        unpaid = status['unpaid_months'] if status else []
        partial = status['partial_months'] if status else []
        
        # Gabungkan unpaid dan partial, lalu urutkan sesuai urutan bulan asli
        available_months = await self.data_manager.get_available_months()
        todo_months = [m for m in available_months if m in unpaid or m in partial]

        if not todo_months:
            msg = f"✅ Semua tagihan untuk *{nama}* sudah lunas!"
            if isinstance(update_or_query, CallbackQuery):
                await update_or_query.edit_message_text(msg, parse_mode='Markdown')
            else:
                await update_or_query.message.reply_text(msg, parse_mode='Markdown')
            return

        keyboard = []
        for month in todo_months[:6]:
            keyboard.append([InlineKeyboardButton(f"Bayar {month}", callback_data=f"pay_mo_{no_warga}_{month}")])

        msg = f"💳 *Input Pembayaran: {nama}*\nPilih bulan yang ingin dibayar:"
        if isinstance(update_or_query, CallbackQuery):
            await update_or_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update_or_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def _show_resident_detail(self, update_or_query, person_data):
        """Helper untuk menampilkan detail tagihan warga"""
        status = await self.data_manager.get_payment_status(person_data['Nama'])
        if not status:
            msg = "❌ Data tidak ditemukan."
            if isinstance(update_or_query, CallbackQuery):
                await update_or_query.edit_message_text(msg)
            else:
                await update_or_query.message.reply_text(msg)
            return

        month_columns = await self.data_manager.get_available_months()
        deadline_info = get_payment_status_info(person_data, month_columns)
        message = format_bill_status(status, month_columns, deadline_info)
        
        # Tampilkan tombol Bayar jika Admin
        reply_markup = None
        user = update_or_query.from_user if isinstance(update_or_query, CallbackQuery) else update_or_query.effective_user
        if is_admin(user.id):
            keyboard = [[InlineKeyboardButton("💳 Input Pembayaran", callback_data=f"pay_sel_{person_data['No']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

        if isinstance(update_or_query, CallbackQuery):
            await update_or_query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            await update_or_query.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)

    async def payment_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        # view_res_ boleh diakses siapa saja
        if data.startswith("view_res_"):
            await query.answer()
            id_warga = data.replace("view_res_", "")
            mask = self.data_manager.df['ID'].astype(str).str.strip() == id_warga.strip()
            if any(mask):
                person = self.data_manager.df[mask].iloc[0].to_dict()
                # Ensure the dict has 'No' key for compatibility if _show_resident_detail needs it
                if 'ID' in person: person['No'] = person['ID']
                await self._show_resident_detail(query, person)
            return

        # st_mo_ boleh diakses siapa saja (mirip tagihan command)
        if data.startswith("st_mo_"):
            await query.answer()
            month_column = data.replace("st_mo_", "")
            stats = await self.data_manager.get_stats(month_column)
            message = format_stats_message(stats)
            
            # Create interactive buttons for months
            keyboard = []
            available_months = stats.get('bulan_tersedia', [])
            
            # Arrange in 4 columns grid
            row = []
            for m in available_months:
                # Highlight selected month with a dot or different style if possible
                # Simple: just keep the same buttons
                row.append(InlineKeyboardButton(m, callback_data=f"st_mo_{m}"))
                if len(row) == 4:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
                
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return

        # Perintah payment lainnya wajib admin
        if not is_admin(user_id):
            await query.answer("⛔ Akses ditolak.", show_alert=True)
            return

        await query.answer()

        if data.startswith("pay_sel_"):
            id_warga = data.replace("pay_sel_", "")
            # Get person from DF
            mask = self.data_manager.df['ID'].astype(str).str.strip() == id_warga.strip()
            person = self.data_manager.df[mask].iloc[0].to_dict()
            if 'ID' in person: person['No'] = person['ID']
            await self._show_pay_months(query, person)

        elif data.startswith("pay_mo_"):
            # Format: pay_mo_ID_MONTH
            parts = data.split("_")
            id_warga = parts[2]
            month = parts[3]
            
            mask = self.data_manager.df['ID'].astype(str).str.strip() == id_warga.strip()
            person = self.data_manager.df[mask].iloc[0]
            
            keyboard = [
                [InlineKeyboardButton("✅ Konfirmasi Bayar Lunas", callback_data=f"pay_cfg_{id_warga}_{month}")],
                [InlineKeyboardButton("💰 Bayar Cicilan", callback_data=f"pay_cic_{id_warga}_{month}")],
                [InlineKeyboardButton("❌ Batal", callback_data="pay_can")]
            ]

            await query.edit_message_text(
                f"❓ *Konfirmasi Pembayaran*\n\n"
                f"👤 *Nama:* {person['Nama']}\n"
                f"📅 *Bulan:* {month}\n"
                f"💵 *Nominal:* {person['Nominal']}\n\n"
                f"Input pembayaran ini ke CSV?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        elif data.startswith("pay_cic_"):
            # Format: pay_cic_ID_MONTH
            parts = data.split("_")
            id_warga = parts[2]
            month = parts[3]
            
            mask = self.data_manager.df['ID'].astype(str).str.strip() == id_warga.strip()
            person = self.data_manager.df[mask].iloc[0]
            
            # Store metadata in user_data for the conversation
            context.user_data['pay_id'] = id_warga
            context.user_data['pay_month'] = month
            context.user_data['pay_name'] = person['Nama']
            
            prompt = (
                f"💰 *Bayar Cicilan: {person['Nama']}*\n"
                f"📅 *Bulan:* {month}\n"
                f"🆔 *ID:* {id_warga}\n\n"
                f"Silakan ketik *nominal cicilan* (angka saja).\n"
                f"Contoh: `50.000` atau `75000`"
            )
            
            if update.effective_message:
                await update.effective_message.reply_text(
                    prompt,
                    parse_mode='Markdown'
                )
            await query.answer()
            return WAITING_AMOUNT

        elif data.startswith("pay_cfg_"):
            parts = data.split("_")
            id_warga = parts[2]
            month = parts[3]
            
            mask = self.data_manager.df['ID'].astype(str).str.strip() == id_warga.strip()
            person = self.data_manager.df[mask].iloc[0]
            nominal = person['Nominal']

            success = await self.data_manager.update_payment(id_warga, month, nominal, is_increment=False)
            if success:
                await query.edit_message_text(f"✅ *Sukses!* Pembayaran {person['Nama']} untuk *{month}* telah dicatat.", parse_mode='Markdown')
            else:
                await query.edit_message_text("❌ *Gagal!* Terjadi kesalahan saat menulis ke file CSV.", parse_mode='Markdown')

        elif data == "pay_can":
            await query.edit_message_text("🚫 Pembayaran dibatalkan.")
            context.user_data.clear()
            return ConversationHandler.END

    async def process_installment_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the WAITING_AMOUNT state in installment conversation"""
        try:
            text = update.effective_message.text if update.effective_message else ""
            amount = parse_nominal(text)
            
            id_warga = context.user_data.get('pay_id')
            month = context.user_data.get('pay_month')
            name = context.user_data.get('pay_name')
            
            if not id_warga or not month:
                if update.effective_message:
                    await update.effective_message.reply_text("❌ Terjadi kesalahan sesi. Silakan ulangi dari awal.")
                context.user_data.clear()
                return ConversationHandler.END

            if amount <= 0:
                if update.effective_message:
                    await update.effective_message.reply_text("❌ Nominal tidak valid. Silakan ketik angka nominal yang benar.")
                return WAITING_AMOUNT

            # Check if user is admin (security check)
            if not is_admin(update.effective_user.id):
                if update.effective_message:
                    await update.effective_message.reply_text("⛔ Hanya admin yang bisa mencatat pembayaran.")
                context.user_data.clear()
                return ConversationHandler.END

            success = await self.data_manager.update_payment(id_warga, month, amount)
            if success:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        f"✅ *Sukses!* Cicilan sebesar *{format_currency(amount)}* "
                        f"untuk *{month}* (ID: {id_warga}) telah dicatat untuk *{name}*.",
                        parse_mode='Markdown'
                    )
            else:
                if update.effective_message:
                    await update.effective_message.reply_text("❌ Terjadi kesalahan saat menulis ke file CSV.")
            
            context.user_data.clear()
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error in process_installment_amount: {e}")
            if update.effective_message:
                await update.effective_message.reply_text("❌ Terjadi kesalahan sistem. Sesi diakhiri.")
            context.user_data.clear()
            return ConversationHandler.END

    async def cancel_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel any active conversation"""
        if update.effective_message:
            await update.effective_message.reply_text("🚫 Sesi dibatalkan.")
        context.user_data.clear()
        return ConversationHandler.END

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Global error handler untuk bot.
        """
        logger.error(f"Update {update} caused error {context.error}")

        # Try to send error message to user
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Terjadi kesalahan. Silakan coba lagi nanti."
                )
        except Exception:
            pass  # Ignore error in error handler


def register_handlers(application, data_manager: BillDataManager):
    """
    Register semua handlers ke application

    Args:
        application: Telegram Bot Application
        data_manager: Instance dari BillDataManager
    """
    handlers = BotHandlers(data_manager)

    # Command handlers
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("stats", handlers.stats_command))
    application.add_handler(CommandHandler("cek", handlers.cek_command))
    application.add_handler(CommandHandler("paid", handlers.paid_command))
    application.add_handler(CommandHandler("bayar", handlers.bayar_command))
    application.add_handler(CommandHandler("reload", handlers.reload_command))

    # Callback Query Handler
    application.add_handler(CallbackQueryHandler(handlers.payment_callback_handler))

    # Text message handler (untuk pencarian langsung)
    application.add_handler(handlers.cek_text_handler)

    # Error handler
    application.add_error_handler(handlers.error_handler)

    logger.info("All handlers registered successfully")
