import torch

from evox.algorithms import DE

from .test_base import TestBase


class TestDEVariants(TestBase):
    def setUp(self):
        pop_size = 10
        dim = 4
        lb = -10 * torch.ones(dim)
        ub = 10 * torch.ones(dim)
        self.algos = [
            DE(pop_size, lb, ub, base_vector="rand"),
            DE(pop_size, lb, ub, base_vector="best"),
        ]

    def test_de_variants(self):
        for algo in self.algos:
            self.run_algorithm(algo)
            self.run_vmap_algorithm(algo)