"""Every command runs under python3 -I, as the importers should when they read files from outside: neither the cwd
nor PYTHONPATH is on sys.path, only the script's own directory.

Run: cd model && python3 -m unittest -v
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
COMMANDS = ["aranceles_no_vigentes.py", "apply.py", "apply_roles.py", "configurar_region.py",
            "convertir_comparacion_ica.py", "crear_cuenta_srtm.py", "import_aranceles.py", "import_fichas.py",
            "import_lotes.py", "import_vias.py", "importar_corte_brecha.py", "vistas_de_mapa.py"]


class IsolatedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cwd = tmp.name

    def run_isolated(self, *args):
        return subprocess.run([sys.executable, "-I", *args], cwd=self.cwd, capture_output=True, text=True, check=False)

    def test_every_command_starts_from_another_directory(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                result = self.run_isolated(os.path.join(HERE, command), "--help")
                self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_a_dry_run_import_reads_its_files_from_another_directory(self):
        fichas = os.path.join(self.cwd, "fichas.csv")
        pisos = os.path.join(self.cwd, "pisos.csv")
        with open(fichas, "w", encoding="utf-8") as f:
            f.write("cod_pre,cod_sect,area_terreno\nA-1,01,100\n")
        with open(pisos, "w", encoding="utf-8") as f:
            f.write("cod_pre,piso,area_construida,material,estado_conservacion,categorias\n"
                    "A-1,1,50,LADRILLO,BUENO,CCDCCDC\n")
        result = self.run_isolated(os.path.join(HERE, "import_fichas.py"), "--fichas", fichas, "--pisos", pisos,
                                   "--dry-run")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_the_model_is_found_from_another_directory(self):
        result = self.run_isolated(os.path.join(HERE, "apply.py"), "--validate-only")
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
