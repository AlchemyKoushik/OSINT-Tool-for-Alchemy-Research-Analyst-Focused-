from backend.services.redis_service import set_session, update_session, get_session

set_session("update_test", {"a": 1})
update_session("update_test", {"b": 2})

print(get_session("update_test"))