"""
Telegram Bot Pembayaran Tagihan - Main Entry Point

Bot ini digunakan untuk mengecek status pembayaran tagihan warga.
Data bersumber dari file CSV yang dapat di-update secara real-time.

Usage:
    python bot_tagihan.py

Commands:
    /start - Menampilkan pesan selamat datang dan bantuan
    /cek <nama> - Mengecek status pembayaran seseorang
    /belum_bayar <bulan> - Melihat siapa yang belum bayar di bulan tertentu
    /stats - Menampilkan statistik data
    /reload - Manual reload data CSV
"""
import asyncio
import logging
import signal
import sys

from telegram import Update
from telegram.ext import Application

# Import config dan modules
from config import (
    BOT_TOKEN,
    MASTER_DATA_PATH,
    BILLING_DATA_DIR,
    DATA_DIR,
    RELOAD_DELAY,
    LOG_LEVEL
)
from src.data_manager import BillDataManager
from src.file_watcher import CSVFileWatcher

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot_tagihan.log', encoding='utf-8')
    ]
)

# Silencing library noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.vendor").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# Global variables
data_manager: BillDataManager = None
file_watcher: CSVFileWatcher = None
application: Application = None


# Sinyal ditangani otomatis oleh application.run_polling()


def shutdown():
    """
    Cleanup resources sebelum exit
    """
    global file_watcher, application

    logger.info("Shutting down bot...")

    # Stop file watcher
    if file_watcher:
        file_watcher.stop()

    logger.info("Bot stopped.")


def register_handlers():
    """
    Register semua command handlers ke application
    """
    from src import handlers as bot_handlers
    from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler

    handlers_instance = bot_handlers.BotHandlers(data_manager)

    # ConversationHandler for installments
    installment_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handlers_instance.payment_callback_handler, pattern="^pay_cic_")
        ],
        states={
            bot_handlers.WAITING_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_instance.process_installment_amount)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", handlers_instance.cancel_conversation),
            MessageHandler(filters.COMMAND, handlers_instance.cancel_conversation)
        ],
        allow_reentry=True,
        name="installment_conversation",
        persistent=False
    )

    # Add ConversationHandler FIRST to catch callbacks before the general handler
    application.add_handler(installment_conv)

    # Command handlers
    application.add_handler(CommandHandler("start", handlers_instance.start_command))
    application.add_handler(CommandHandler("help", handlers_instance.help_command))
    application.add_handler(CommandHandler("stats", handlers_instance.stats_command))
    application.add_handler(CommandHandler("cek", handlers_instance.cek_command))
    application.add_handler(CommandHandler("tagihan", handlers_instance.tagihan_command))
    application.add_handler(CommandHandler("paid", handlers_instance.paid_command))
    application.add_handler(CommandHandler("bayar", handlers_instance.bayar_command))
    application.add_handler(CommandHandler("reload", handlers_instance.reload_command))

    # Callback Query Handler for general payments (except pay_cic_ which is handled by conv)
    application.add_handler(CallbackQueryHandler(handlers_instance.payment_callback_handler))

    # Text message handler (untuk pencarian langsung, bukan command)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handlers_instance.cek_text_handler
        )
    )

    # Error handler
    application.add_error_handler(handlers_instance.error_handler)

    logger.info("All handlers registered successfully")


async def post_init(application: Application):
    """
    Callback setelah application di-initialize
    """
    from telegram import BotCommand
    
    # Set bot commands untuk menu
    commands = [
        BotCommand("start", "Mulai & Tampilkan Menu"),
        BotCommand("cek", "Cek tagihan warga (Nama)"),
        BotCommand("tagihan", "Lihat yang belum bayar"),
        BotCommand("paid", "Lihat yang sudah bayar"),
        BotCommand("stats", "Statistik tagihan"),
        BotCommand("help", "Bantuan penggunaan")
    ]
    await application.bot.set_my_commands(commands)
    
    logger.info("Bot initialized successfully and commands menu set!")


def main():
    """
    Main function untuk menjalankan bot
    """
    global data_manager, file_watcher, application

    logger.info("=" * 50)
    logger.info("Telegram Bot Pembayaran Tagihan")
    logger.info("=" * 50)

    # Sinyal ditangani otomatis oleh application.run_polling()
    # signal.signal(signal.SIGINT, signal_handler)
    # signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize Data Manager
        logger.info(f"Loading master data: {MASTER_DATA_PATH}")
        logger.info(f"Loading billing dir: {BILLING_DATA_DIR}")
        data_manager = BillDataManager(str(MASTER_DATA_PATH), str(BILLING_DATA_DIR))

        if data_manager.df.empty:
            logger.error("Gagal memuat data CSV atau file kosong!")
            sys.exit(1)

        stats = data_manager.get_stats_sync()
        logger.info(f"Data loaded: {stats['total_warga']} warga, {stats['total_bulan']} bulan")

        # Initialize File Watcher
        logger.info(f"Starting file watcher on: {DATA_DIR}")
        file_watcher = CSVFileWatcher(
            data_dir=str(DATA_DIR),
            reload_callback=lambda: (
                logger.info("Data reloaded successfully") if data_manager.reload_data_sync()
                else logger.error("Failed to reload data")
            ),
            delay=RELOAD_DELAY
        )

        if not file_watcher.start():
            logger.warning("Failed to start file watcher. Continuing without auto-reload.")
        else:
            data_manager.set_file_watcher(file_watcher)

        # Create Application
        logger.info("Creating Telegram application...")
        application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

        # Register handlers
        register_handlers()

        # Start bot
        logger.info("Starting bot polling...")
        logger.info("Bot is ready! Press Ctrl+C to stop.")

        # Run bot
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        shutdown()


if __name__ == "__main__":
    main()
