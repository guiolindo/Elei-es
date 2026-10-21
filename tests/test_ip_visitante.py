from starlette.requests import Request

from app.main import ip_do_visitante, limiter


def _req(headers=None, client=("100.64.0.7", 4000)):
    scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"",
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             "client": client}
    return Request(scope)


def test_usa_o_primeiro_ip_do_x_forwarded_for():
    # Atrás do proxy do Railway a conexão vem do proxy; o visitante é o 1º do XFF.
    assert ip_do_visitante(_req({"X-Forwarded-For": "189.6.10.20, 100.64.0.2"})) == "189.6.10.20"


def test_cai_para_x_real_ip_e_depois_para_a_conexao():
    assert ip_do_visitante(_req({"X-Real-IP": "177.1.2.3"})) == "177.1.2.3"
    assert ip_do_visitante(_req()) == "100.64.0.7"


def test_visitantes_diferentes_nao_dividem_o_limite():
    a = ip_do_visitante(_req({"X-Forwarded-For": "189.6.10.20"}))
    b = ip_do_visitante(_req({"X-Forwarded-For": "201.17.4.9"}))
    assert a != b


def test_limite_comporta_varias_pessoas_no_mesmo_ip():
    # ~25 req/min por visitante na apuração; o limite precisa caber vários.
    (lim,) = [l for grupo in limiter._default_limits for l in grupo]
    assert lim.limit.amount >= 500
