from abc import ABC
from typing import Optional, Final, Union, Any

import torch
from torch import nn

from module import ModuleBase, jit_class, trace_impl
from jit_util import vmap


class Algorithm(ModuleBase, ABC):
    """Base class for all algorithms"""
    pop_size: Final[int]
    
    def __init__(self, pop_size: int):
        super().__init__()
        assert pop_size > 0, f"Population size shall be larger than 0"
        self.pop_size = pop_size
    
    def init_ask(self) -> torch.Tensor:
        """Ask the algorithm for the first time, defaults to `self.ask()`.

        Workflows only call `init_ask()` for one time, the following asks will all invoke `ask()`.

        Returns:
            `torch.Tensor`: The initial candidate solution.
        """
        return self.ask()
    
    def ask(self) -> torch.Tensor:
        """Ask the algorithm.

        Ask the algorithm for points to explore.

        Returns:
            `torch.Tensor`: The candidate solution.
        """
        raise NotImplementedError()
    
    def init_tell(self, fitness: torch.Tensor) -> None:
        """Tell the algorithm more information, defaults to `self.tell(fitness)`.

        Workflows only call `init_tell()` for one time, the following tells will all invoke `tell()`.

        Args:
            fitness (`torch.Tensor`): The fitness.
        """
        return self.tell(fitness)
    
    def tell(self, fitness: torch.Tensor) -> None:
        """Tell the algorithm more information.

        Tell the algorithm about the points it chose and their corresponding fitness.

        Args:
            fitness (`torch.Tensor`): The fitness.
        """
        raise NotImplementedError()


class Problem(ModuleBase, ABC):
    """Base class for all problems"""
    num_obj: Final[int]
    
    def __init__(self, num_objective: int):
        super().__init__()
        assert num_objective > 0, f"Number of objectives shall be larger than 0"
        self.num_obj = num_objective
    
    def evaluate(self, pop: Union[torch.Tensor, Any]) -> torch.Tensor:
        """Evaluate the fitness at given points

        Args:
            pop (`torch.Tensor` or any): The population.

        Returns:
            `torch.Tensor`: The fitness.
        """
        raise NotImplementedError()
    
    def eval(self):
        assert False, "Problem.eval() shall never be invoked to prevent ambiguity."


class Workflow(ModuleBase, ABC):
    """The base class for workflow."""
    
    def step(self) -> None:
        """The basic function to step a workflow.

        Usually consists of sequence invocation of `algorithm.ask()`, `problem.evaluate()`, and `algorithm.tell()`.
        """
        raise NotImplementedError()
    
    def loop(self, max_iterations: Optional[int] = None) -> None:
        """Loop the workflow until the maximum number of iterations (`max_iterations`) is reached.

        Args:
            max_iterations (`int`, optional): The desired maximum number of iterations.
            If it is None, this workflow must contains attribute `max_iterations`.
        """
        raise NotImplementedError()


class Monitor(ModuleBase, ABC):
    """
    The monitor base class.

    Monitors are used to monitor the evolutionary process.
    They contains a set of callbacks,
    which will be called at specific points during the execution of the workflow.
    Monitor itself lives outside the main workflow, so jit is not required.

    To implements a monitor, implement your own callbacks and override the hooks method.
    The hooks method should return a list of strings, which are the names of the callbacks.
    Currently the supported callbacks are:

    `pre_step`, `post_step`, `pre_ask`, `post_ask`, `pre_eval`, `post_eval`, `pre_tell`, `post_tell`, and `post_step`.
    """
    
    def __init__(self):
        raise NotImplementedError()
    
    def set_opt_direction(self, opt_direction):
        raise NotImplementedError()
    
    def hooks(self):
        raise NotImplementedError
    
    def pre_step(self):
        raise NotImplementedError()
    
    def pre_ask(self):
        raise NotImplementedError()
    
    def post_ask(self, candidate_solution: Union[torch.Tensor, Any]):
        raise NotImplementedError()
    
    def pre_eval(
        self,
        candidate_solution: Union[torch.Tensor, Any],
        transformed_candidate_solution: Union[torch.Tensor, Any],
    ):
        raise NotImplementedError()
    
    def post_eval(
        self,
        candidate_solution: Union[torch.Tensor, Any],
        transformed_candidate_solution: Union[torch.Tensor, Any],
        fitness: torch.Tensor,
    ):
        raise NotImplementedError()
    
    def pre_tell(
        self,
        candidate_solution: Union[torch.Tensor, Any],
        transformed_candidate_solution: Union[torch.Tensor, Any],
        fitness: torch.Tensor,
        transformed_fitness: torch.Tensor,
    ):
        raise NotImplementedError()
    
    def post_tell(self):
        raise NotImplementedError()
    
    def post_step(self):
        raise NotImplementedError()


# Test
if __name__ == "__main__":
    
    class BasicProblem(Problem):
        
        def __init__(self):
            super().__init__(num_objective=1)
            self._eval_fn = vmap(BasicProblem._single_eval, example_ndim=2)
        
        def _single_eval(x: torch.Tensor, p: float = 2.0):
            return (x**p).sum()
        
        def evaluate(self, pop):
            return self._eval_fn(pop)
    
    class BasicAlgorithm(Algorithm):
        
        def __init__(self, pop_size: int, lb: torch.Tensor, ub: torch.Tensor):
            super().__init__(pop_size=pop_size)
            assert lb.ndim == 1 and ub.ndim == 1, f"Lower and upper bounds shall have ndim of 1, got {lb.ndim} and {ub.ndim}"
            assert lb.shape == ub.shape, f"Lower and upper bounds shall have same shape, got {lb.ndim} and {ub.ndim}"
            self.lb = lb
            self.ub = ub
            self.pop = nn.Buffer(torch.empty(pop_size, lb.shape[0], dtype=lb.dtype, device=lb.device))
            self.fit = nn.Buffer(torch.empty(pop_size, dtype=lb.dtype, device=lb.device))
        
        def ask(self):
            pop = torch.rand(self.pop_size, self.lb.shape[0], dtype=self.lb.dtype, device=self.lb.device)
            pop = pop * (self.ub - self.lb)[torch.newaxis, :] + self.lb[torch.newaxis, :]
            self.pop = pop
            return self.pop
        
        def tell(self, fitness):
            self.fit = fitness
    
    @jit_class
    class BasicWorkflow(Workflow):
        
        def __init__(self, algorithm: Algorithm, problem: Problem, device: Optional[Union[str, torch.device, int]] = None):
            super().__init__()
            algorithm = algorithm.to(device=device)
            problem = problem.to(device=device)
            self.algorithm = algorithm
            self.problem = problem
            self.generation = nn.Buffer(torch.zeros((), dtype=torch.int32, device=device))
        
        def step(self):
            population = self.algorithm.ask() if self.generation > 1 else self.algorithm.init_ask()
            fitness = self.problem.evaluate(population)
            self.algorithm.tell(fitness) if self.generation > 1 else self.algorithm.init_tell(fitness)
            self.generation += 1
        
        @trace_impl(step)
        def trace_step(self):
            population = torch.select(self.generation > 1, self.algorithm.ask(), self.algorithm.init_ask())
            fitness = self.problem.evaluate(population)
            torch.select(self.generation > 1, self.problem.tell(fitness), self.problem.init_tell(fitness))
            self.generation += 1
        
        def loop(self, max_iterations: int):
            for _ in range(max_iterations):
                self.step()
    
    torch.set_default_device("cuda" if torch.cuda.is_available() else "cpu")
    algo = BasicAlgorithm(100, -10 * torch.ones(5), 10 * torch.ones(5))
    prob = BasicProblem()
    workflow = BasicWorkflow(algo, prob)
    print(workflow.step.inlined_graph)
    print(workflow.trace_step)
    workflow.step()
    print(workflow.generation, workflow.algorithm.fit)
    workflow.step()
    print(workflow.generation, workflow.algorithm.fit)
    
    workflow = BasicWorkflow(algo, prob)
    workflow.loop(100)
    print(workflow.algorithm.fit)