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
            logging.warning(
                "🚨 Memory usage %.1f MB > critical threshold %.1f MB — forced GC",
                current_memory / (1024 * 1024),
                self.critical_threshold / (1024 * 1024),
            )
            self.force_cleanup()
            return False

        if current_memory > self.warning_threshold and (
            time.time() - self.last_gc_time > self.gc_interval
        ):
            logging.info(
                "⚠️ Memory usage %.1f MB > warning threshold %.1f MB — GC",
                current_memory / (1024 * 1024),
                self.warning_threshold / (1024 * 1024),
            )
            self.force_cleanup()
        
        return True

    def force_cleanup(self):
        logging.info("🧹 Запуск garbage collection (GC)...")
        gc.collect()
        self.last_gc_time = time.time()
        logging.info("✅ Очистка памяти завершена.")