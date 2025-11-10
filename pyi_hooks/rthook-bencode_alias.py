# Em runtime, se 'bencode' não existir, redireciona para 'bencode.py' (bencodepy)
import sys

try:
    import bencode  # noqa: F401
except Exception:
    try:
        import bencodepy as _b
        sys.modules["bencode"] = _b
    except Exception:
        # último recurso: tenta 'bencode' do pacote bencode.py se existir
        pass
