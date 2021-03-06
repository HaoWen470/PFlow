from geomloss.utils import squared_distances, distances
import torch
from pflow.base import BaseReweight
import math
from pflow.utils.fix_for_geomloss_losses import SamplesLoss


def transport_from_potentials(x, f, g, eps, logw, n, p):
    """
    To get the transported particles from the sinkhorn iterates

    :param x: torch.Tensor[N, D]
        Input: the state variable
    :param f: torch.Tensor[N]
        Potential, output of the sinkhorn iterates
    :param g: torch.Tensor[N]
        Potential, output of the sinkhorn iterates
    :param eps: float
    :param logw: torch.Tensor[N]
    :param n: int
    :param p: int
    :return: torch.Tensor[N, D], torch.Tensor[N]
    """
    if p == 1:
        cost = distances(x, x) / p
    else:
        cost = squared_distances(x, x) / p
    fg = f.T + g
    denominator = eps ** p

    temp = (fg - cost)
    temp.clamp_min(-3 * denominator * math.log(n))
    temp /= denominator

    transport_matrix = (temp + logw.unsqueeze(0)).exp() / n
    transport_matrix /= transport_matrix.sum(1).unsqueeze(1)

    return transport_matrix @ x, torch.full_like(logw, math.log(1/n), requires_grad=True)


def solve_for_state(x, logw, loss, n):
    
    """
    Use Geomloss to find the transportation potentials for (x, w) to (w, 1/N)

    :param x: torch.Tensor[N, D]
        The input
    :param logw: torch.Tensor[N]
        The degenerate logweights
    :param loss: geomloss.SamplesLoss
        Needs to be biased for the potentials to correspond to a proper plan
    :param n: int
    :return: torch.Tensor[N], torch.Tensor[N]
        the potentials
    """
    uniform_weights = torch.full_like(logw, math.log(1 / n))
    alpha, beta = loss(uniform_weights, x, logw, x)
    return alpha, beta


def transport(x, logw, w, loss, eps, p):
    """
    Combine solve_for_state and transport_from_potentials in a "reweighting scheme"
    :param x: torch.Tensor[N, D]
        The input
    :param logw: torch.Tensor[N]
        The degenerate logweights
    :param logw: torch.Tensor[N]
        The degenerate weights
    :param loss: geomloss.SamplesLoss
        Needs to be biased for the potentials to correspond to a proper plan
    :param eps: float
        Blur parameter used in loss
    :param p: float
        Power of cost function
    """
    n = x.shape[0]
    alpha, beta = solve_for_state(x, logw, loss, n)
    x_tilde, logw_tilde = transport_from_potentials(x, alpha, beta, eps, logw, n, p)
    return x_tilde, logw_tilde


class Transport(BaseReweight):
    def __init__(self, epsilon, **geomloss_kwargs):
        self.epsilon = epsilon
        geomloss_kwargs.pop('blur', None)
        geomloss_kwargs.pop('potentials', None)
        geomloss_kwargs.pop('debias', None)
        self.p = geomloss_kwargs.pop('p', 2)
        self.sample_loss = SamplesLoss(blur=epsilon, debias=False, potentials=True, p=self.p,
                                       is_log=True, **geomloss_kwargs)

    def apply(self, x, w, logw):
        return transport(x, logw, w, self.sample_loss, self.epsilon, self.p)
