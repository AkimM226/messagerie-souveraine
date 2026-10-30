"""Tests des règles de classification. Lancer : python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
from classification import niveau_du_nom, renommage_autorise  # noqa: E402

NIVEAUX = {"[CONFIDENTIEL]": 300, "[DIFFUSION RESTREINTE]": 604800}


class TestNiveau(unittest.TestCase):
    def test_reconnait_le_niveau_sans_tenir_compte_de_la_casse(self):
        self.assertEqual(niveau_du_nom("[confidentiel] Cellule de crise", NIVEAUX), "[CONFIDENTIEL]")
        self.assertEqual(niveau_du_nom("  [DIFFUSION RESTREINTE] Budget", NIVEAUX), "[DIFFUSION RESTREINTE]")

    def test_salon_ordinaire_ou_sans_nom(self):
        self.assertIsNone(niveau_du_nom("Pause café", NIVEAUX))
        self.assertIsNone(niveau_du_nom(None, NIVEAUX))
        self.assertIsNone(niveau_du_nom("Note [CONFIDENTIEL]", NIVEAUX))  # le niveau doit être en tête


class TestRenommage(unittest.TestCase):
    def test_salon_ordinaire_libre(self):
        self.assertTrue(renommage_autorise("Équipe", "Autre nom", NIVEAUX))
        self.assertTrue(renommage_autorise(None, "[CONFIDENTIEL] X", NIVEAUX))

    def test_meme_niveau_ou_plus_strict_autorise(self):
        self.assertTrue(renommage_autorise("[CONFIDENTIEL] A", "[CONFIDENTIEL] B", NIVEAUX))
        self.assertTrue(renommage_autorise("[DIFFUSION RESTREINTE] A", "[CONFIDENTIEL] A", NIVEAUX))

    def test_declassement_interdit(self):
        self.assertFalse(renommage_autorise("[CONFIDENTIEL] A", "A", NIVEAUX))
        self.assertFalse(renommage_autorise("[CONFIDENTIEL] A", "[DIFFUSION RESTREINTE] A", NIVEAUX))
        self.assertFalse(renommage_autorise("[CONFIDENTIEL] A", "", NIVEAUX))


if __name__ == "__main__":
    unittest.main()
