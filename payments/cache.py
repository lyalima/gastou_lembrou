import hashlib
import json

from django.conf import settings
from django.core.cache import cache


PAYMENT_LIST_FILTERS = (
    "q",
    "category",
    "payment_method",
    "day",
    "month",
    "year",
    "schedule_status",
    "order",
)


def invalidate_user_payment_cache(user_id):
    version_key = _user_payment_cache_version_key(user_id)
    if cache.add(version_key, 2, timeout=None):
        return
    try:
        cache.incr(version_key)
    except ValueError:
        cache.set(version_key, 2, timeout=None)


def get_cached_payment_ids(user_id, query_params, queryset_builder):
    cache_key = _payment_list_cache_key(user_id, query_params)
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids

    payment_ids = [str(payment_id) for payment_id in queryset_builder()]
    cache.set(cache_key, payment_ids, timeout=settings.PAYMENT_LIST_CACHE_TIMEOUT)
    return payment_ids


def _payment_list_cache_key(user_id, query_params):
    version = cache.get(_user_payment_cache_version_key(user_id), 1)
    signature = _payment_list_filter_signature(query_params)
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return f"payments:list:{user_id}:v{version}:{digest}"


def _payment_list_filter_signature(query_params):
    values = {}
    for key in PAYMENT_LIST_FILTERS:
        value = query_params.get(key)
        if value not in (None, ""):
            values[key] = value
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def _user_payment_cache_version_key(user_id):
    return f"payments:user:{user_id}:version"
