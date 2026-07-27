from fastapi import Request
from slowapi import Limiter


def get_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("x-forwarded-for")

    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = request.headers.get("x-real-ip")

    if x_real_ip:
        return x_real_ip.strip()

    if request.client:
        return request.client.host

    return "127.0.0.1"


limiter = Limiter(key_func=get_client_ip)
