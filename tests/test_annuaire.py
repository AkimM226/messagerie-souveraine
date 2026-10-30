"""Tests des règles de synchronisation avec l'annuaire. Lancer : python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))
from annuaire import comptes_a_revoquer, nom_affiche  # noqa: E402


class TestNomAffiche(unittest.TestCase):
    def test_fiche_complete(self):
        agent = {"username": "awa.ouedraogo", "firstName": "Awa", "lastName": "Ouédraogo",
                 "attributes": {"fonction": ["Cheffe de service"], "direction": ["DRH"], "ministere": ["MTDPCE"]}}
        self.assertEqual(nom_affiche(agent), "Awa Ouédraogo · Cheffe de service · DRH · MTDPCE")

    def test_fiche_incomplete(self):
        self.assertEqual(nom_affiche({"username": "x", "firstName": "Awa", "attributes": {"direction": ["DRH"]}}),
                         "Awa · DRH")
        self.assertEqual(nom_affiche({"username": "agent.sans.nom"}), "agent.sans.nom")


class TestRevocation(unittest.TestCase):
    COMPTES = {"id-awa": "@awa:m", "id-ibrahim": "@ibrahim:m", "id-fatimata": "@fatimata:m"}

    def test_revoque_ce_qui_n_est_plus_autorise(self):
        # Ibrahim désactivé (ou supprimé, ou privé du rôle agent) : absent des autorisés.
        self.assertEqual(comptes_a_revoquer(self.COMPTES, {"id-awa", "id-fatimata"}), ["@ibrahim:m"])

    def test_tout_le_monde_autorise(self):
        self.assertEqual(comptes_a_revoquer(self.COMPTES, {"id-awa", "id-ibrahim", "id-fatimata", "id-autre"}), [])

    def test_lecture_vide_ne_revoque_personne(self):
        # Une réponse vide de Keycloak est une anomalie : on ne désactive pas toute l'administration.
        self.assertEqual(comptes_a_revoquer(self.COMPTES, set()), [])


if __name__ == "__main__":
    unittest.main()
