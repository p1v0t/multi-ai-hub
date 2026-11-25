"""Local dashboard; opening it never enables automatic dispatch."""
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
import hub
from local_http import LocalError, LocalHandler, LocalServer


class Handler(LocalHandler):
    def do_GET(self):
        try:
            path = urlparse(self.path).path
            self.guard(api=path.startswith("/api/"))
            if path in ("/", "/hub"):
                self.serve_html(Path(__file__).resolve().parent / "static" / "hub.html")
            elif path == "/api/hub":
                self.send_json(hub.estado_api())
            else:
                self.send_json({"error": "Não encontrado."}, 404)
        except LocalError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except Exception:
            self.send_json({"error": "Falha interna. Confira a configuração local."}, 500)

    def do_POST(self):
        try:
            self.guard(api=True, mutation=True)
            body = self.read_json()
            if body.get("confirm") is not True:
                raise LocalError("Confirmação obrigatória.")
            path = urlparse(self.path).path
            if path not in ("/api/hub/pausar", "/api/hub/retomar"):
                self.send_json({"error": "Não encontrado."}, 404)
                return
            with hub._TRAVA_CICLO:
                hub.definir_auto(path.endswith("retomar"))
            self.send_json({"ok": True})
        except LocalError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except Exception:
            self.send_json({"error": "Falha interna. Confira a configuração local."}, 500)


def main():
    port = int(os.environ.get("AI_HUB_PORT", "8766"))
    try:
        server = LocalServer(("127.0.0.1", port), Handler)
    except OSError:
        print("Porta ocupada. Feche a outra instância ou configure AI_HUB_PORT.", file=sys.stderr)
        return 1
    # Every dashboard restart is paused, even if the previous session was enabled.
    hub.definir_auto(False)
    dispatcher = hub.iniciar_em_segundo_plano()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Multi-AI Hub em {url}. Despacho pausado. Ctrl+C encerra o painel.")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hub.definir_auto(False)
        dispatcher.parar.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
