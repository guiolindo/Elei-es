from app.visitas import _classificar_ua


def test_navegadores_contam_como_visita():
    chrome = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
    assert _classificar_ua(chrome) == ("Chrome", False)
    safari = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
    assert _classificar_ua(safari) == ("Safari", False)


def test_ferramentas_e_robos_nao_contam():
    for ua in ("curl/8.5.0", "python-httpx/0.27", "Python-urllib/3.11",
               "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 HeadlessChrome/130.0 Safari/537.36",
               "Googlebot/2.1", ""):
        assert _classificar_ua(ua)[1] is True, ua
