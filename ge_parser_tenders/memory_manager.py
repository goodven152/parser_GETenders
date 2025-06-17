import gc
import time
import logging
import psutil


class MemoryManager:
    def __init__(self, warning_threshold_mb=1000, critical_threshold_mb=1500, gc_interval=60):
        self.warning_threshold = warning_threshold_mb * 1024 * 1024
        self.critical_threshold = critical_threshold_mb * 1024 * 1024
        self.last_gc_time = time.time()
        self.gc_interval = gc_interval  # секунды между сборками мусора

    def check_memory(self) -> bool:
        current_memory = psutil.Process().memory_info().rss

        if current_memory > self.critical_threshold:
            logging.debug(f"🔍 Текущая память: {current_memory / (1024 * 1024):.2f} MB")
            self.force_cleanup()
            return False

        if current_memory > self.warning_threshold:
            if time.time() - self.last_gc_time > self.gc_interval:
                logging.warning("🚨 Достигнут критический порог памяти! Принудительная очистка...")
                self.force_cleanup()

        if current_memory > self.warning_threshold:
            if time.time() - self.last_gc_time > self.gc_interval:
                logging.info("⚠️ Высокое потребление памяти. Запуск очистки...")
                self.force_cleanup()
        
        return True

    def force_cleanup(self):
        logging.debug("🧹 Запуск garbage collection (GC)...")
        gc.collect()
        self.last_gc_time = time.time()
        logging.debug("✅ Очистка памяти завершена.")