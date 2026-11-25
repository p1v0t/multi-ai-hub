#!/usr/bin/env python3
"""Trava de arquivos + fila + dono por tarefa — Multi-AI Hub.

Sem pacotes externos. Evita que dois agentes (claude, codex, grok, kiro...) mexam
no mesmo arquivo ou pasta ao mesmo tempo, e que duas IAs façam a mesma tarefa.

Arquivos
  pegar    <caminhos...> --agente A --tarefa "T" [--min 60]   reserva (arquivo ou pasta)
  liberar  <caminhos...> --agente A                          devolve (ou --tudo)
  renovar  --agente A [--min 60]                             estende as travas do agente
  checar   <caminho> --agente A                              0 = pode editar, 1 = de outro (para ganchos)
  status                                                     lista travas e fila
Tarefas
  tarefa-nova     "titulo" --arquivos a b ... [--id ID]
  tarefa-assumir  ID --agente A      (também trava os arquivos da tarefa)
  tarefa-concluir ID --agente A      (libera os arquivos e registra no CHANGELOG)
  tarefa-pausar   ID [--motivo ...]  (preserva histórico; libera travas/fila da tarefa)
  tarefa-retomar  ID                (volta a aberta; tarefa-assumir reserva novamente)
  tarefas

Regras
- Trava vale para o caminho e tudo abaixo dele (trava de pasta cobre os arquivos).
- Trava expira sozinha (padrão 60 min) se o agente não renovar: ninguém fica preso.
- Quem encontra o caminho travado entra na fila e vai fazer outra tarefa.
  Ao liberar, o primeiro da fila tem 10 min de preferência para pegar.
- Caminhos podem ser absolutos (Windows ou Linux) ou relativos à raiz do projeto.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from settings import PROJECT as P, DATA
D = DATA / "locks"
ESTADO = D / "estado.json"
MUTEX = D / ".mutex"
QUADRO = D / "TRAVAS_E_TAREFAS.md"
CHANGELOG = D / "CHANGELOG.md"
PREFERENCIA_S = 600


# ---------- utilidades ----------

def agora():
    return time.time()


def hora(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


def norm(caminho):
    c = str(caminho).strip().strip('"').replace("\\", "/")
    if not c or "\x00" in c or ":" in c.replace(str(P.drive), "", 1):
        raise ValueError("Caminho inválido")
    candidate = Path(c)
    path = (candidate if candidate.is_absolute() else P / candidate).resolve()
    try:
        rel = path.relative_to(P.resolve()).as_posix()
    except ValueError:
        raise ValueError("Caminho fora do projeto") from None
    return rel.lower() if os.name == "nt" else rel


def cobre(a, b):
    """True se a trava em `a` e o caminho `b` se sobrepõem (um contém o outro)."""
    return a == "." or b == "." or a == b or b.startswith(a + "/") or a.startswith(b + "/")


class Mutex:
    """Exclusão mútua por arquivo criado atomicamente (O_EXCL)."""

    def __enter__(self):
        D.mkdir(parents=True, exist_ok=True)
        fim = agora() + 15
        while True:
            try:
                fd = os.open(str(MUTEX), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                if agora() > fim:
                    sys.exit("TRAVA|ERRO|mutex ocupado; tente de novo")
                time.sleep(0.1)

    def __exit__(self, *a):
        try:
            MUTEX.unlink()
        except FileNotFoundError:
            pass


def carregar():
    if ESTADO.exists():
        e = json.loads(ESTADO.read_text(encoding="utf-8"))
    else:
        e = {}
    e.setdefault("travas", [])
    e.setdefault("fila", [])
    e.setdefault("tarefas", [])
    e.setdefault("preferencias", [])
    t = agora()
    e["travas"] = [x for x in e["travas"] if x["expira"] > t]
    e["preferencias"] = [x for x in e["preferencias"] if x["ate"] > t]
    return e


def salvar(e):
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ESTADO)
    escrever_quadro(e)


def escrever_quadro(e):
    L = ["# Travas e tarefas (gerado por trava.py — não editar à mão)", "",
         f"Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", "", "## Travas ativas"]
    L += [f"- `{x['caminho']}` — **{x['agente']}** — {x['tarefa']} — até {hora(x['expira'])}" for x in e["travas"]] or ["- (nenhuma)"]
    L += ["", "## Fila"]
    L += [f"- `{x['caminho']}` ← {x['agente']} ({x['tarefa']}) desde {hora(x['desde'])}" for x in e["fila"]] or ["- (vazia)"]
    L += ["", "## Tarefas"]
    for s in ("andamento", "aberta", "pausada", "concluida"):
        for x in e["tarefas"]:
            if x["status"] == s:
                dono = f" — dono **{x['dono']}**" if x.get("dono") else ""
                L.append(f"- [{s}] **{x['id']}** {x['titulo']}{dono} — arquivos: {', '.join(x['arquivos']) or '-'}")
    QUADRO.write_text("\n".join(L) + "\n", encoding="utf-8")


def conflitos(e, caminho, agente):
    return [x for x in e["travas"] if cobre(x["caminho"], caminho) and x["agente"] != agente]


def preferencia_de_outro(e, caminho, agente):
    return [x for x in e["preferencias"] if cobre(x["caminho"], caminho) and x["agente"] != agente]


def changelog(linha):
    try:
        with open(CHANGELOG, "a", encoding="utf-8") as f:
            f.write(f"\n- {datetime.now().strftime('%Y-%m-%d %H:%M')} · {linha}\n")
    except OSError:
        pass


# ---------- comandos ----------

def pegar(e, caminhos, agente, tarefa, minutos):
    t = agora()
    normais = [norm(c) for c in caminhos]
    bloqueios = []
    for c in normais:
        for x in conflitos(e, c, agente):
            bloqueios.append((c, f"travado por {x['agente']} ({x['tarefa']}) até {hora(x['expira'])}"))
        for x in preferencia_de_outro(e, c, agente):
            bloqueios.append((c, f"preferência de {x['agente']} (primeiro da fila) até {hora(x['ate'])}"))
    if bloqueios:   # tudo ou nada: não pega metade
        for c, motivo in bloqueios:
            print(f"TRAVA|OCUPADO|{c}|{motivo}")
            if not any(f["caminho"] == c and f["agente"] == agente for f in e["fila"]):
                e["fila"].append({"caminho": c, "agente": agente, "tarefa": tarefa, "desde": t})
        print("TRAVA|NA_FILA|vá para outra tarefa e tente de novo depois")
        return 1
    for c in normais:
        e["travas"] = [x for x in e["travas"] if not (x["caminho"] == c and x["agente"] == agente)]
        e["travas"].append({"caminho": c, "agente": agente, "tarefa": tarefa, "desde": t, "expira": t + minutos * 60})
        e["fila"] = [f for f in e["fila"] if not (f["caminho"] == c and f["agente"] == agente)]
        e["preferencias"] = [p for p in e["preferencias"] if not (p["caminho"] == c and p["agente"] == agente)]
        print(f"TRAVA|OK|{c}|{agente}|até {hora(t + minutos * 60)}")
    return 0


def liberar(e, caminhos, agente, tudo=False):
    alvo = [x for x in e["travas"] if x["agente"] == agente and (tudo or x["caminho"] in {norm(c) for c in caminhos})]
    for x in alvo:
        e["travas"].remove(x)
        print(f"TRAVA|LIBERADO|{x['caminho']}")
        espera = [f for f in e["fila"] if cobre(f["caminho"], x["caminho"])]
        if espera:
            prox = espera[0]
            e["preferencias"].append({"caminho": prox["caminho"], "agente": prox["agente"], "ate": agora() + PREFERENCIA_S})
            print(f"TRAVA|PROXIMO|{prox['caminho']}|{prox['agente']} tem 10 min de preferência")
    if not alvo:
        print("TRAVA|NADA|nenhuma trava desse agente nesses caminhos")
    return 0


def renovar(e, agente, minutos):
    n = 0
    for x in e["travas"]:
        if x["agente"] == agente:
            x["expira"] = agora() + minutos * 60
            n += 1
    print(f"TRAVA|RENOVADO|{agente}|{n} travas")
    return 0


def checar(e, caminho, agente):
    c = norm(caminho)
    outros = conflitos(e, c, agente)
    if outros:
        x = outros[0]
        print(f"TRAVA|BLOQUEADO|{c}|de {x['agente']} ({x['tarefa']}) até {hora(x['expira'])}")
        return 1
    print(f"TRAVA|LIVRE|{c}")
    return 0


def status(e):
    print(QUADRO.read_text(encoding="utf-8") if QUADRO.exists() else "(sem quadro)")
    return 0


def tarefa_nova(e, titulo, arquivos, tid):
    tid = tid or f"T{len(e['tarefas']) + 1:03d}"
    if any(x["id"] == tid for x in e["tarefas"]):
        print(f"TAREFA|ERRO|id {tid} já existe")
        return 1
    parecidas = [x for x in e["tarefas"] if x["status"] != "concluida" and
                 any(cobre(norm(a), b) for a in arquivos for b in x["arquivos"])]
    e["tarefas"].append({"id": tid, "titulo": titulo, "arquivos": [norm(a) for a in arquivos],
                         "status": "aberta", "dono": "", "criada": agora()})
    print(f"TAREFA|CRIADA|{tid}|{titulo}")
    for x in parecidas:
        print(f"TAREFA|AVISO|toca os mesmos arquivos que {x['id']} ({x['titulo']}, {x['status']}, dono {x['dono'] or '-'})")
    return 0


def tarefa_assumir(e, tid, agente):
    x = next((t for t in e["tarefas"] if t["id"] == tid), None)
    if not x:
        print(f"TAREFA|ERRO|{tid} não existe")
        return 1
    if x["dono"] and x["dono"] != agente and x["status"] == "andamento":
        print(f"TAREFA|OCUPADA|{tid} já é de {x['dono']}")
        return 1
    r = pegar(e, x["arquivos"], agente, f"{tid} {x['titulo']}", 60) if x["arquivos"] else 0
    if r:
        return r
    x["dono"], x["status"] = agente, "andamento"
    print(f"TAREFA|ASSUMIDA|{tid}|{agente}")
    return 0


def tarefa_concluir(e, tid, agente):
    x = next((t for t in e["tarefas"] if t["id"] == tid), None)
    if not x or x["dono"] != agente:
        print(f"TAREFA|ERRO|{tid} não é de {agente}")
        return 1
    liberar(e, x["arquivos"], agente)
    x["status"] = "concluida"
    changelog(f"{agente} · tarefa {tid} concluída: {x['titulo']} (arquivos liberados)")
    print(f"TAREFA|CONCLUIDA|{tid}")
    return 0


def da_tarefa(registro, tid):
    """pegar aceita ID ou 'ID título'; nunca confundir T001 com T0010."""
    partes = registro.get("tarefa", "").split(maxsplit=1)
    return bool(partes) and partes[0] == tid


def tarefa_pausar(e, tid, motivo):
    x = next((t for t in e["tarefas"] if t["id"] == tid), None)
    if not x:
        print(f"TAREFA|ERRO|{tid} não existe")
        return 1
    if x["status"] == "pausada":
        print(f"TAREFA|PAUSADA|{tid}|já pausada")
        return 0
    if x["status"] not in ("aberta", "andamento"):
        print(f"TAREFA|ERRO|{tid} não pode pausar no estado {x['status']}")
        return 1

    travas = [r for r in e["travas"] if da_tarefa(r, tid)]
    fila = [r for r in e["fila"] if da_tarefa(r, tid)]
    # Cancelar a espera ANTES de liberar: a tarefa pausada não recebe preferência.
    e["fila"] = [r for r in e["fila"] if not da_tarefa(r, tid)]
    chaves_canceladas = {(r["caminho"], r["agente"]) for r in fila}
    chaves_restantes = {(r["caminho"], r["agente"]) for r in e["fila"]}
    preferencias = [r for r in e["preferencias"] if da_tarefa(r, tid) or (
        not r.get("tarefa") and (r["caminho"], r["agente"]) in
        chaves_canceladas - chaves_restantes)]
    e["preferencias"] = [r for r in e["preferencias"] if r not in preferencias]
    for trava in travas:
        liberar(e, [trava["caminho"]], trava["agente"])
    x.setdefault("historico", []).append({
        "acao": "pausar", "em": agora(), "motivo": motivo,
        "status_anterior": x["status"], "dono": x.get("dono", ""),
        "travas_liberadas": travas, "fila_cancelada": fila,
        "preferencias_canceladas": preferencias,
    })
    x["status"] = "pausada"
    print(f"TAREFA|PAUSADA|{tid}")
    return 0


def tarefa_retomar(e, tid):
    x = next((t for t in e["tarefas"] if t["id"] == tid), None)
    if not x:
        print(f"TAREFA|ERRO|{tid} não existe")
        return 1
    if x["status"] != "pausada":
        print(f"TAREFA|ERRO|{tid} não está pausada")
        return 1
    # Retomar não apropria arquivos nem restaura reservas que podem ter outro dono.
    x.setdefault("historico", []).append({
        "acao": "retomar", "em": agora(), "status_anterior": "pausada",
        "dono": x.get("dono", ""),
    })
    x["status"] = "aberta"
    print(f"TAREFA|RETOMADA|{tid}|aberta; use tarefa-assumir para reservar os arquivos")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("pegar"); a.add_argument("caminhos", nargs="+"); a.add_argument("--agente", required=True); a.add_argument("--tarefa", required=True); a.add_argument("--min", type=int, default=60)
    a = sp.add_parser("liberar"); a.add_argument("caminhos", nargs="*"); a.add_argument("--agente", required=True); a.add_argument("--tudo", action="store_true")
    a = sp.add_parser("renovar"); a.add_argument("--agente", required=True); a.add_argument("--min", type=int, default=60)
    a = sp.add_parser("checar"); a.add_argument("caminho"); a.add_argument("--agente", required=True)
    sp.add_parser("status")
    a = sp.add_parser("tarefa-nova"); a.add_argument("titulo"); a.add_argument("--arquivos", nargs="*", default=[]); a.add_argument("--id", default="")
    a = sp.add_parser("tarefa-assumir"); a.add_argument("id"); a.add_argument("--agente", required=True)
    a = sp.add_parser("tarefa-concluir"); a.add_argument("id"); a.add_argument("--agente", required=True)
    a = sp.add_parser("tarefa-pausar"); a.add_argument("id"); a.add_argument("--motivo", default="")
    a = sp.add_parser("tarefa-retomar"); a.add_argument("id")
    sp.add_parser("tarefas")
    g = ap.parse_args()
    ag = g.agente.strip().lower() if getattr(g, "agente", None) else None
    with Mutex():
        e = carregar()
        if g.cmd == "pegar": r = pegar(e, g.caminhos, ag, g.tarefa, g.min)
        elif g.cmd == "liberar": r = liberar(e, g.caminhos, ag, g.tudo)
        elif g.cmd == "renovar": r = renovar(e, ag, g.min)
        elif g.cmd == "checar": r = checar(e, g.caminho, ag)
        elif g.cmd in ("status", "tarefas"):
            salvar(e); return status(e)
        elif g.cmd == "tarefa-nova": r = tarefa_nova(e, g.titulo, g.arquivos, g.id)
        elif g.cmd == "tarefa-assumir": r = tarefa_assumir(e, g.id, ag)
        elif g.cmd == "tarefa-pausar": r = tarefa_pausar(e, g.id, g.motivo)
        elif g.cmd == "tarefa-retomar": r = tarefa_retomar(e, g.id)
        else: r = tarefa_concluir(e, g.id, ag)
        salvar(e)
    return r


if __name__ == "__main__":
    sys.exit(main())
