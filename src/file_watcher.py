"""
Module untuk monitor perubahan file CSV menggunakan watchdog
"""
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileMovedEvent

logger = logging.getLogger(__name__)


class DebouncedFileHandler(FileSystemEventHandler):
    """
    File handler dengan debounce untuk menghindari multiple reload
    saat file CSV diubah (misal: saat save di Excel bisa trigger multiple events)
    """

    def __init__(self, callback: Callable[[], None], delay: float = 1.0):
        """
        Initialize DebouncedFileHandler

        Args:
            callback: Fungsi yang dipanggil setelah delay
            delay: Delay dalam detik untuk debounce
        """
        super().__init__()
        self.callback = callback
        self.delay = delay
        self.last_call = 0
        self.timer: Optional[threading.Timer] = None
        self.lock = threading.Lock()
        self.paused = False

    def on_modified(self, event):
        """
        Dipanggil saat file dimodifikasi
        """
        with self.lock:
            if self.paused: return

        # Hanya proses file CSV
        if not event.is_directory and event.src_path.endswith('.csv'):
            self._schedule_reload()

    def on_moved(self, event):
        """
        Dipanggil saat file dipindahkan/rename
        """
        with self.lock:
            if self.paused: return

        # Hanya proses file CSV
        if not event.is_directory and event.dest_path.endswith('.csv'):
            self._schedule_reload()

    def _schedule_reload(self):
        """
        Schedule reload dengan debounce
        """
        with self.lock:
            current_time = time.time()

            # Cancel timer yang sudah ada
            if self.timer is not None:
                self.timer.cancel()

            # Schedule new timer
            self.timer = threading.Timer(self.delay, self._execute_callback)
            self.timer.start()

            self.last_call = current_time

    def _execute_callback(self):
        """
        Execute callback di thread terpisah
        """
        try:
            logger.info("File CSV berubah, menjalankan reload...")
            self.callback()
        except Exception as e:
            logger.error(f"Error saat execute callback: {e}")

    def stop(self):
        """
        Stop timer jika ada
        """
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None

    def pause(self):
        """Pause processing of file events"""
        with self.lock:
            self.paused = True
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            logger.info("File watcher processing paused.")

    def resume(self):
        """Resume processing of file events"""
        with self.lock:
            self.paused = False
            logger.info("File watcher processing resumed.")


class CSVFileWatcher:
    """
    Class untuk monitor perubahan file CSV di directory data dan auto-reload.
    """

    def __init__(self, data_dir: str, reload_callback: Callable[[], None], delay: float = 1.0):
        """
        Initialize CSVFileWatcher

        Args:
            data_dir: Root directory data (e.g. 'data/')
            reload_callback: Fungsi yang dipanggil saat ada file CSV berubah
            delay: Delay dalam detik untuk debounce
        """
        self.data_dir = Path(data_dir).resolve()
        self.reload_callback = reload_callback
        self.delay = delay
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[DebouncedFileHandler] = None

    def start(self) -> bool:
        """
        Mulai monitoring directory data
        """
        try:
            if not self.data_dir.exists():
                logger.error(f"Directory tidak ditemukan: {self.data_dir}")
                return False

            self.event_handler = DebouncedFileHandler(
                callback=self.reload_callback,
                delay=self.delay
            )

            self.observer = Observer()
            # Watch root data dir recursively to catch billing/*.csv and master_clients.csv
            self.observer.schedule(
                self.event_handler,
                str(self.data_dir),
                recursive=True
            )
            self.observer.start()

            logger.info(f"Memulai monitoring directory: {self.data_dir}")
            return True

        except Exception as e:
            logger.error(f"Error saat memulai file watcher: {e}")
            return False

    def stop(self):
        """
        Stop monitoring file CSV
        """
        try:
            if self.event_handler:
                self.event_handler.stop()

            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=5)

            logger.info("File watcher dihentikan")

        except Exception as e:
            logger.error(f"Error saat menghentikan file watcher: {e}")

    def pause(self):
        """Pause file event processing"""
        if self.event_handler:
            self.event_handler.pause()

    def resume(self):
        """Resume file event processing"""
        if self.event_handler:
            self.event_handler.resume()

    def is_running(self) -> bool:
        """
        Cek apakah watcher sedang running

        Returns:
            bool: True jika running, False jika tidak
        """
        return self.observer is not None and self.observer.is_alive()


if __name__ == "__main__":
    # Test
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    def test_callback():
        logger.info("=== CALLBACK DIPANGGIL ===")

    watcher = CSVFileWatcher("bahrulhuda.csv", test_callback, delay=2.0)
    watcher.start()

    print("File watcher started. Edit bahrulhuda.csv to test...")
    print("Press Ctrl+C to stop")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        watcher.stop()
