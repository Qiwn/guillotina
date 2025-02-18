from guillotina import app_settings
from guillotina.contrib.cache.lru import LRU


_lru = None


def get_memory_cache():
    global _lru
    if _lru is None:
        settings = app_settings.get('cache', {
            'memory_cache_size': 209715200
        })
        _lru = LRU(settings['memory_cache_size'])
    return _lru
