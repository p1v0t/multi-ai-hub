import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class HubSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / "demo.txt").write_text("before", encoding="utf-8")
        self.env = patch.dict(os.environ, {"AI_HUB_PROJECT": str(self.project), "AI_HUB_HOME": str(self.base / "state")})
        self.env.start()
        for name in ("settings", "hub", "trava"):
            sys.modules.pop(name, None)
        self.h = importlib.import_module("hub")
        self.h.garantir_pastas()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def lock(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / "trava.py"), *args], capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout

    def test_paused_default_never_starts_cli(self):
        self.h.nova("TASK-1", "Demo", "codex", ["demo.txt"], "Review")
        with patch.object(self.h.subprocess, "Popen") as popen:
            self.h.Despachante().ciclo()
        popen.assert_not_called()
        self.assertFalse(self.h.config()["auto"])
        self.assertFalse(self.h.config()["auto_apply_reviews"])

    def test_missing_project_fails_before_creating_state(self):
        with patch.dict(os.environ, {"AI_HUB_PROJECT": ""}):
            with self.assertRaises(RuntimeError):
                sys.modules["settings"].paths()

    def test_runtime_inside_project_rejected(self):
        with patch.dict(os.environ, {"AI_HUB_HOME": str(self.project / "state")}):
            with self.assertRaises(RuntimeError):
                sys.modules["settings"].paths()

    def test_invalid_task_ids_rejected_everywhere(self):
        for tid in ("../escape", "a/b", "a\\b", "CON", "NUL.json", "ok\n", "bad."):
            for function in (self.h.onde, self.h.assumir, self.h.aprovar):
                with self.subTest(tid=tid, operation=function.__name__), self.assertRaises(ValueError):
                    function(tid)
            with self.assertRaises(ValueError): self.h.devolver(tid, "review")

    def test_dependency_id_validated(self):
        with self.assertRaises(ValueError):
            self.h.nova("TASK-1", "Demo", "grok", [], "Review", depende=["../outside"])

    def test_path_escape_and_windows_stream_rejected(self):
        for path in ("../outside", "demo.txt:secret", str(self.base / "outside")):
            with self.subTest(path=path), self.assertRaises(ValueError): self.h.absoluto(path)

    def test_symlink_or_junction_escape_rejected(self):
        external = self.base / "outside"; external.mkdir()
        link = self.project / "link"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            if os.name != "nt": raise
            # Synthetic directories only; paths contain no untrusted shell syntax.
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(external)], capture_output=True)
            self.assertEqual(result.returncode, 0, "Cannot create junction for security test")
        try:
            with self.assertRaises(ValueError): self.h.absoluto("link/new.txt")
        finally:
            if link.is_symlink(): link.unlink()
            else: os.rmdir(link)

    def test_locks_normalize_traversal_and_cover_root(self):
        self.assertEqual(self.lock("pegar", ".", "--agente", "agent-a", "--tarefa", "TASK-1")[0], 0)
        self.assertEqual(self.lock("checar", "sub/../demo.txt", "--agente", "agent-b")[0], 1)
        self.assertEqual(self.lock("liberar", "--tudo", "--agente", "agent-a")[0], 0)
        self.assertEqual(self.lock("checar", "demo.txt", "--agente", "agent-b")[0], 0)

    def test_lock_rejects_external_path(self):
        self.assertNotEqual(self.lock("pegar", "../outside", "--agente", "a", "--tarefa", "x")[0], 0)

    def test_backup_failure_prevents_launch(self):
        task = self.h.nova("TASK-2", "Demo", "codex", ["demo.txt"], "Review")
        with patch.object(self.h.shutil, "copy2", side_effect=OSError("synthetic failure")), \
             patch.object(self.h, "trava", return_value=(0, "available")), \
             patch.object(self.h.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError): self.h.Despachante().iniciar(task)
        popen.assert_not_called()
        self.assertTrue(task.exists())

    def test_backup_contains_files_in_task_directory(self):
        directory = self.project / "folder"; directory.mkdir()
        (directory / "one.txt").write_text("one")
        files = self.h.backup_no_arquivo({"id": "TASK-3", "arquivos": ["folder"]})
        self.assertEqual(len(files), 1)
        self.assertEqual(Path(files[0]).read_text(), "one")

    def test_backup_retries_do_not_overwrite_snapshot(self):
        task = {"id": "TASK-4", "arquivos": ["demo.txt"]}
        first = self.h.backup_no_arquivo(task)
        (self.project / "demo.txt").write_text("after")
        second = self.h.backup_no_arquivo(task)
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first[0]).read_text(), "before")
        self.assertEqual(Path(second[0]).read_text(), "after")

    def test_dependency_blocks_dispatch(self):
        self.h.nova("TASK-5", "Demo", "codex", [], "Review", depende=["WAIT"])
        self.h.definir_auto(True)
        with patch.object(self.h.Despachante, "iniciar") as start:
            self.h.Despachante().ciclo()
        start.assert_not_called()

    def test_invalid_config_fails_closed(self):
        self.h.CONFIG.write_text("{broken")
        self.assertFalse(self.h.config()["auto"])

    def test_completion_review_approval_flow(self):
        task = self.h.nova("TASK-6", "Demo", "codex", ["demo.txt"], "Review")
        data = self.h.ler(task)
        data["hash_antes"] = self.h.hashes(data["arquivos"])
        running = self.h.mover(data, task, "execucao")
        (self.project / "demo.txt").write_text("updated")
        (self.h.HUB / "entregas/TASK-6.md").write_text("Done")
        self.h.Despachante().concluir(running, "entrega gravada")
        review = self.h.HUB / "revisao/TASK-6.json"
        self.assertEqual(self.h.ler(review)["alterados"], ["demo.txt"])
        self.assertTrue((self.h.HUB / "fila/REV-TASK-6.json").is_file())
        self.h.aprovar("TASK-6", "Reviewed")
        self.assertTrue((self.h.HUB / "aprovadas/TASK-6.json").is_file())

    def test_real_synthetic_executor_end_to_end(self):
        # Python fixture only: never invokes an AI, shell, account or external service.
        script = self.base / "executor.py"
        delivery = self.h.HUB / "entregas/TASK-7.md"
        script.write_text("from pathlib import Path\nPath(" + repr(str(delivery)) + ").write_text('done')\n")
        cfg = self.h.config(); cfg["auto"] = True
        cfg["cmd"]["codex"] = [sys.executable, str(script)]
        self.h.gravar(self.h.CONFIG, cfg)
        task = self.h.nova("TASK-7", "Synthetic", "codex", [], "Fixture")
        dispatcher = self.h.Despachante(); dispatcher.iniciar(task)
        process = dispatcher.processos["TASK-7"]
        self.assertEqual(process.wait(timeout=5), 0)
        dispatcher.concluir(self.h.HUB / "execucao/TASK-7.json", "entrega gravada")
        self.assertTrue(delivery.is_file())
        self.assertTrue((self.h.HUB / "revisao/TASK-7.json").is_file())


if __name__ == "__main__":
    unittest.main()
