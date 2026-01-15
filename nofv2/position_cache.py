import threading

# 线程安全的持仓缓存
_position_lock = threading.Lock()
_position_records = set()

class ThreadSafePositionRecords:
    """线程安全的持仓记录集合"""
    
    def clear(self):
        with _position_lock:
            _position_records.clear()
    
    def update(self, symbols):
        with _position_lock:
            _position_records.update(symbols)
    
    def add(self, symbol):
        with _position_lock:
            _position_records.add(symbol)
    
    def discard(self, symbol):
        with _position_lock:
            _position_records.discard(symbol)
    
    def __contains__(self, symbol):
        with _position_lock:
            return symbol in _position_records
    
    def __iter__(self):
        with _position_lock:
            return iter(list(_position_records))
    
    def __len__(self):
        with _position_lock:
            return len(_position_records)
    
    def __bool__(self):
        with _position_lock:
            return bool(_position_records)
    
    def copy(self):
        with _position_lock:
            return _position_records.copy()

# 导出线程安全的实例
position_records = ThreadSafePositionRecords()