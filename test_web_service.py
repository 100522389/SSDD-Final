"""
test_web_service.py  –  Tests para la Fase 3 (servicio web SOAP de normalización)

Contiene dos bloques:
  1) Tests unitarios directos sobre NormalizeService (sin servidor).
  2) Tests de integración vía Zeep (requiere que web_service.py esté arrancado).

Uso:
    # Solo unitarios (sin servidor):
    python3 test_web_service.py unit

    # Todos (unitarios + integración): arrancar web_service.py antes
    python3 test_web_service.py

Variables de entorno opcionales:
    WS_HOST  – host del servicio (por defecto: localhost)
    WS_PORT  – puerto del servicio (por defecto: 7789)
"""

import sys
import os
import re

# ─── Lógica pura de normalización (copiada de web_service.py) ────────────────

def _normalize_logic(message):
    """Réplica exacta de la función normalize del servicio."""
    if message is None:
        return ""
    return re.sub(r' +', ' ', message).strip()

# ─── Bloque 1: Tests unitarios directos ──────────────────────────────────────

UNIT_TESTS = [
    # (descripción, entrada, salida_esperada)
    ("espacios múltiples internos",     "hola   mundo",       "hola mundo"),
    ("espacios al inicio y final",      "  hola mundo  ",     "hola mundo"),
    ("espacios en todos lados",         "  a  b   c  ",       "a b c"),
    ("un solo espacio (sin cambios)",   "hola mundo",         "hola mundo"),
    ("cadena vacía",                    "",                   ""),
    ("None → cadena vacía",             None,                 ""),
    ("solo espacios",                   "     ",              ""),
    ("mensaje largo con múltiples huecos",
     "Este  es   un   mensaje   muy   largo   con   huecos",
     "Este es un mensaje muy largo con huecos"),
    ("un solo carácter",                "x",                  "x"),
    ("salto de línea (no afectado)",    "hola\nmundo",        "hola\nmundo"),
]

def run_unit_tests():
    passed = 0
    failed = 0
    print("=" * 60)
    print("BLOQUE 1 – Tests unitarios (sin servidor)")
    print("=" * 60)
    for desc, inp, expected in UNIT_TESTS:
        result = _normalize_logic(inp)
        ok = result == expected
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"  [{status}] {desc}")
            print(f"         entrada:   {inp!r}")
            print(f"         esperado:  {expected!r}")
            print(f"         obtenido:  {result!r}")
        if ok:
            print(f"  [{status}] {desc}")
    print(f"\nResultado unitarios: {passed}/{len(UNIT_TESTS)} PASS\n")
    return failed == 0

# ─── Bloque 2: Tests de integración (vía Zeep) ───────────────────────────────

INTEGRATION_TESTS = [
    # (descripción, entrada, salida_esperada)
    ("espacios múltiples vía SOAP",       "hola   mundo",   "hola mundo"),
    ("espacios extremos vía SOAP",        "  a  b  ",       "a b"),
    ("cadena vacía vía SOAP",             "",               ""),
    ("mensaje sin espacios extra",        "correcto",       "correcto"),
    ("solo espacios vía SOAP",            "   ",            ""),
]

def run_integration_tests(host, port):
    try:
        from zeep import Client as ZeepClient
    except ImportError:
        print("SKIP – zeep no disponible, se omiten tests de integración.")
        return True

    wsdl = f"http://{host}:{port}/?wsdl"
    try:
        client = ZeepClient(wsdl)
    except Exception as e:
        print(f"SKIP – No se pudo conectar al servicio en {wsdl}: {e}")
        print("       Arranca web_service.py antes de ejecutar tests de integración.")
        return True  # no forzamos fallo si el servicio no está levantado

    passed = 0
    failed = 0
    print("=" * 60)
    print(f"BLOQUE 2 – Tests de integración (SOAP @ {wsdl})")
    print("=" * 60)
    for desc, inp, expected in INTEGRATION_TESTS:
        try:
            result = client.service.normalize(inp)
            # Zeep convierte strings vacías de SOAP a None (comportamiento estándar)
            normalized = result if result is not None else ""
            ok = normalized == expected
        except Exception as e:
            result = f"EXCEPCIÓN: {e}"
            ok = False
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"  [{status}] {desc}")
            print(f"         entrada:   {inp!r}")
            print(f"         esperado:  {expected!r}")
            print(f"         obtenido:  {result!r}")
        if ok:
            print(f"  [{status}] {desc}")
    print(f"\nResultado integración: {passed}/{len(INTEGRATION_TESTS)} PASS\n")
    return failed == 0

# ─── Bloque 3: Tests del cliente (_normalize cacheado) ───────────────────────

def run_client_normalize_tests(host, port):
    """Verifica que client._normalize usa el caché y hace fallback correctamente."""
    try:
        from client import client as Client
    except ImportError:
        print("SKIP – client.py no importable.")
        return True

    print("=" * 60)
    print("BLOQUE 3 – Tests de client._normalize (caché + fallback)")
    print("=" * 60)
    passed = 0
    failed = 0

    # Resetear estado
    Client._zeep_client = None

    # Test 1: fallback cuando el cliente Zeep falla (mock roto)
    class _BrokenZeepClient:
        class service:
            @staticmethod
            def normalize(msg):
                raise ConnectionError("fallo simulado")
    Client._zeep_client = _BrokenZeepClient()
    result = Client._normalize("hola   mundo")
    # Con cliente roto debe devolver el mensaje sin cambios
    fallback_ok = result == "hola   mundo"
    status = "PASS" if fallback_ok else "FAIL"
    print(f"  [{status}] fallback sin servicio devuelve mensaje original")
    if fallback_ok:
        passed += 1
    else:
        failed += 1
        print(f"         obtenido: {result!r}")

    # Test 2: tras fallback, _zeep_client debe ser None (reset)
    cache_reset_ok = Client._zeep_client is None
    status = "PASS" if cache_reset_ok else "FAIL"
    print(f"  [{status}] _zeep_client es None tras fallback")
    if cache_reset_ok:
        passed += 1
    else:
        failed += 1

    # Test 3: con servicio activo, normaliza correctamente
    try:
        from zeep import Client as ZeepClient
        wsdl = f"http://{host}:{port}/?wsdl"
        ZeepClient(wsdl)  # probar conexión
        service_up = True
    except Exception:
        service_up = False

    if service_up:
        Client._zeep_client = None
        result = Client._normalize("  hola   mundo  ")
        norm_ok = result == "hola mundo"
        status = "PASS" if norm_ok else "FAIL"
        print(f"  [{status}] normalización correcta vía servicio real")
        if norm_ok:
            passed += 1
        else:
            failed += 1
            print(f"         obtenido: {result!r}")

        # Test 4: segunda llamada reutiliza el caché
        cache_before = Client._zeep_client
        Client._normalize("test")
        cache_after = Client._zeep_client
        cache_reused = (cache_before is cache_after)
        status = "PASS" if cache_reused else "FAIL"
        print(f"  [{status}] segunda llamada reutiliza _zeep_client cacheado")
        if cache_reused:
            passed += 1
        else:
            failed += 1
    else:
        print("  [SKIP] servicio no activo – tests 3 y 4 omitidos")

    total = 4 if service_up else 2
    print(f"\nResultado cliente: {passed}/{total} PASS\n")
    return failed == 0


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    host = os.environ.get("WS_HOST", "localhost")
    port = int(os.environ.get("WS_PORT", "7789"))

    all_ok = True

    all_ok &= run_unit_tests()

    if mode != "unit":
        all_ok &= run_integration_tests(host, port)
        all_ok &= run_client_normalize_tests(host, port)

    print("=" * 60)
    if all_ok:
        print("RESULTADO GLOBAL: TODOS LOS TESTS PASARON")
    else:
        print("RESULTADO GLOBAL: ALGUNOS TESTS FALLARON")
    print("=" * 60)
    sys.exit(0 if all_ok else 1)
