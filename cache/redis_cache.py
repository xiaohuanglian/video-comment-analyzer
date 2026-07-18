# -*- coding: utf-8 -*-
# @Name    : Programmer AJiang-Relakkes
# @Time    : 2024/5/29 22:57
# @Desc    : RedisCache implementation
import pickle
import time
from typing import Any, List

from redis import Redis
from redis.exceptions import ResponseError

from cache.abs_cache import AbstractCache
from config import db_config


class RedisCache(AbstractCache):

    def __init__(self) -> None:
        # Connect to redis, return redis client
        self._redis_client = self._connet_redis()

    @staticmethod
    def _connet_redis() -> Redis:
        """
        Connect to redis, return redis client, configure redis connection information as needed
        :return:
        """
        return Redis(
            host=db_config.REDIS_DB_HOST,
            port=db_config.REDIS_DB_PORT,
            db=db_config.REDIS_DB_NUM,
            password=db_config.REDIS_DB_PWD,
        )

    def get(self, key: str) -> Any:
        """
        Get the value of a key from the cache and deserialize it
        :param key:
        :return:
        """
        value = self._redis_client.get(key)
        if value is None:
            return None
        return pickle.loads(value)

    def set(self, key: str, value: Any, expire_time: int) -> None:
        """
        Set the value of a key in the cache and serialize it
        :param key:
        :param value:
        :param expire_time:
        :return:
        """
        self._redis_client.set(key, pickle.dumps(value), ex=expire_time)

    def keys(self, pattern: str) -> List[str]:
        """
        Get all keys matching the pattern
        First try KEYS command, if not supported fallback to SCAN
        """
        try:
            # Try KEYS command first (faster for standard Redis)
            return [key.decode() if isinstance(key, bytes) else key for key in self._redis_client.keys(pattern)]
        except ResponseError as e:
            # If KEYS is not supported (e.g., Redis Cluster or cloud Redis), use SCAN
            if "unknown command" in str(e).lower() or "keys" in str(e).lower():
                keys_list: List[str] = []
                cursor = 0
                while True:
                    cursor, keys = self._redis_client.scan(cursor=cursor, match=pattern, count=100)
                    keys_list.extend([key.decode() if isinstance(key, bytes) else key for key in keys])
                    if cursor == 0:
                        break
                return keys_list
            else:
                # Re-raise if it's a different error
                raise


if __name__ == '__main__':
    redis_cache = RedisCache()
    # basic usage
    redis_cache.set("name", "Programmer AJiang-Relakkes", 1)
    print(redis_cache.get("name"))  # Relakkes
    print(redis_cache.keys("*"))  # ['name']
    time.sleep(2)
    print(redis_cache.get("name"))  # None

    # special python type usage
    # list
    redis_cache.set("list", [1, 2, 3], 10)
    _value = redis_cache.get("list")
    print(_value, f"value type:{type(_value)}")  # [1, 2, 3]
