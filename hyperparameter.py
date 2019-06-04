import torch
import torch.nn as nn
from torch.distributions.constraints import positive, simplex

import pyro
import pyro.distributions as dist
from pyro.infer import config_enumerate, SVI, TraceEnum_ELBO
from pyro.optim import Adam, Adagrad

import matplotlib.pyplot as plt

from tqdm import tqdm

class BPF(object):

    def __init__(self, hyperparams):
        super().__init__()
        self.hyperparams = hyperparams

    def _model(self, ratings):
        if hyperparams is None:
            hyperparams = self.hyperparams

        user_mean_dist = dist.Gamma(hyperparams['a_u'], hyperparams['b_u'])
        item_mean_dist = dist.Gamma(hyperparams['a_i'], hyperparams['b_i'])

        with pyro.plate('users_loop', hyperparams['num_users']):
            user_mean = pyro.sample('user_mean', user_mean_dist)
            user_latents_dist = dist.Gamma(hyperparams['c_u'], user_mean)
            with pyro.plate('user_latents', hyperparams['num_latents']):
                user_latents = pyro.sample('user_latents', user_latents_dist)

        with pyro.plate('items_loop', hyperparams['num_items']):
            item_mean = pyro.sample('item_mean', item_mean_dist)
            item_latents_dist = dist.Gamma(hyperparams['c_u'], item_mean)
            with pyro.plate('item_latents',  hyperparams['num_latents']):
                item_latents = pyro.sample('item_latents', item_latents_dist)

        ratings_itr = iter(ratings)
        with pyro.plate('ratings', hyperparams['num_nonmissing']):
            user, item, rating = next(ratings_itr)
            lam = user_latents[:, user] @ item_latents[:, item]
            pyro.sample('obs_rating', dist.Poisson(lam), obs=rating)

    def _guide(self, ratings, hyperparams=None):
        if hyperparams is None:
            hyperparams = self.hyperparams

        for u in pyro.plate('users_loop', hyperparams['num_users']):
            # Variational parameters per user
            q_au = pyro.param('q_au_{}'.format(u), hyperparams['a_u'],
                              constraint=positive)
            q_bu = pyro.param('q_bu_{}'.format(u), hyperparams['b_u'],
                              constraint=positive)
            user_mean_dist = dist.Gamma(q_au, q_bu)
            user_mean = pyro.sample('user_mean', user_mean_dist)

            # Sample latents
            for l in pyro.plate('user_latents', hyperparams['num_latents']):
                q_lu1 = pyro.param('q_lu1_{},{}'.format(u, l), hyperparams['c_u'],
                                   constraint=positive)
                q_lu2 = pyro.param('q_lu2_{},{}'.format(u, l), torch.tensor(1.),
                                   constraint=positive)
                user_latents_dist = dist.Gamma(q_lu1, q_lu2)
                user_latents = pyro.sample('user_latents', user_latents_dist)

        for i in pyro.plate('items_loop', hyperparams['num_items']):
            # Variational parameters per item
            q_ai = pyro.param('q_ai_{}'.format(i), hyperparams['a_i'],
                              constraint=positive)
            q_bi = pyro.param('q_bi_{}'.format(i), hyperparams['b_i'],
                              constraint=positive)
            item_mean_dist = dist.Gamma(q_ai, q_bi)
            item_mean = pyro.sample('item_mean', item_mean_dist)

            # Sample latents
            for l in pyro.plate('item_latents', hyperparams['num_latents']):
                q_li1 = pyro.param('q_li1_{},{}'.format(i, l), hyperparams['c_i'],
                                   constraint=positive)
                q_li2 = pyro.param('q_li2_{},{}'.format(i, l), torch.tensor(1.),
                                   constraint=positive)
                item_latents_dist = dist.Gamma(q_li1, q_li2)
                item_latents = pyro.sample('item_latents', item_latents_dist)

    def fit(self, ratings, hyperparams=None, num_steps=2000):
        if hyperparams is None:
            if self.hyperparams is None:
                raise ValueError('Hyperparameters not provided!')
            else:
                self.hyperparams = hyperparams
        else:
            hyperparams = self.hyperparams

        optim = Adam({'lr': 0.1, 'betas': [0.8, 0.99]})
        svi = SVI(self._model, config_enumerate(self._guide, 'sequential'), optim, loss=TraceEnum_ELBO())
        losses = []
        for s in tqdm(range(num_steps)):
            loss = svi.step(ratings, hyperparams)
            losses.append(loss)

        return losses

class MMPF(object):

    def __init__(self, hyperparams):
        super().__init__()
        self.hyperparams = hyperparams

    def _model(self, ratings):
        user_mean_dist = dist.Gamma(self.hyperparams['a_u'], self.hyperparams['b_u'])
        item_mean_dist = dist.Gamma(self.hyperparams['a_i'], self.hyperparams['b_i'])

        context_dist = dist.Gamma(self.hyperparams['a_c'], self.hyperparams['b_c'])
        context_prob_dist = dist.Dirichlet(self.hyperparams['context_conc'] * torch.ones(self.hyperparams['num_contexts']))

        user_context_prob = pyro.sample('user_context_prob', context_prob_dist)
        item_context_prob = pyro.sample('item_context_prob', context_prob_dist)

        for c in pyro.plate('user_contexts', self.hyperparams['num_contexts']):
            for v in pyro.plate('user_context_latents_{}'.format(c),  self.hyperparams['num_context_latents']):
                user_context_latents = pyro.sample('user_context_latents_{},{}'.format(c, v),
                                                   dist.Gamma(self.hyperparams['a_c'], self.hyperparams['b_c']))

        for c in pyro.plate('item_contexts', self.hyperparams['num_contexts']):
            for v in pyro.plate('item_context_latents_{}'.format(c), self.hyperparams['num_context_latents']):
                item_context_latents = pyro.sample('item_context_latents_{},{}'.format(c, v),
                                                   dist.Gamma(self.hyperparams['a_c'], self.hyperparams['b_c']))

        for u in pyro.plate('users_loop', self.hyperparams['num_users']):
            user_mean = pyro.sample('user_mean_{}'.format(u), user_mean_dist)
            user_latents_dist = dist.Gamma(self.hyperparams['c_u'], user_mean)
            for k in pyro.plate('user_latents_loop_{}'.format(u), self.hyperparams['num_latents']):
                user_latents = pyro.sample('user_latents_{},{}'.format(u, k), user_latents_dist)

        for i in pyro.plate('items_loop', self.hyperparams['num_items']):
            item_mean = pyro.sample('item_mean_{}'.format(i), item_mean_dist)
            item_latents_dist = dist.Gamma(self.hyperparams['c_i'], item_mean)
            for k in pyro.plate('item_latents_loop_{}'.format(i),  self.hyperparams['num_latents']):
                item_latents = pyro.sample('item_latents_{},{}'.format(i, k), item_latents_dist)

        ratings_itr = iter(ratings)
        for j in pyro.plate('ratings', self.hyperparams['num_nonmissing']):
            user, item, rating = next(ratings_itr)
            z_u = pyro.sample('user_context_{},{}'.format(user, item), dist.Categorical(user_context_prob))
            z_i = pyro.sample('item_context_{},{}'.format(user, item), dist.Categorical(item_context_prob))
            lam = user_latents[:, user] @ item_latents[:, item] + \
                user_context_latents[:, z_u] @ item_context_latents[:, z_i]
            pyro.sample('obs_rating_{},{}'.format(user, item), dist.Poisson(lam), obs=rating)

    def _guide(self, ratings, hyperparams=None):
        q_user_context_conc = pyro.param('q_user_context_conc', torch.ones(self.hyperparams['num_context_latents']),
                                         constraint=positive)
        q_item_context_conc = pyro.param('q_item_context_conc', torch.ones(self.hyperparams['num_context_latents']),
                                         constraint=positive)
        user_context_prob = pyro.sample('user_context_prob', dist.Dirichlet(q_user_context_conc))
        item_context_prob = pyro.sample('item_context_prob', dist.Dirichlet(q_item_context_conc))

        for c in pyro.plate('user_contexts_loop', self.hyperparams['num_contexts']):
            for v in pyro.plate('user_context_latents_loop_{}'.format(c), self.hyperparams['num_context_latents']):
                q_aucv = pyro.param('q_aucv_{},{}'.format(c, v), self.hyperparams['a_c'],
                              constraint=positive)
                q_bucv = pyro.param('q_bucv_{},{}'.format(c, v), self.hyperparams['b_c'],
                              constraint=positive)
                user_context_latents = pyro.sample('user_context_latents_{},{}'.format(c, v), dist.Gamma(q_aucv, q_bucv))


        for c in pyro.plate('item_contexts_loop', self.hyperparams['num_contexts']):
            for v in pyro.plate('item_context_latents_loop_{}'.format(c), self.hyperparams['num_context_latents']):
                q_aicv = pyro.param('q_aicv_{},{}'.format(c, v), self.hyperparams['a_c'],
                              constraint=positive)
                q_bicv = pyro.param('q_bicv_{},{}'.format(c, v), self.hyperparams['b_c'],
                              constraint=positive)
                item_context_latents = pyro.sample('item_context_latents_{},{}'.format(c, v), dist.Gamma(q_aicv, q_bicv))

        for u in pyro.plate('users_loop', self.hyperparams['num_users']):
            # Variational parameters per user
            q_au = pyro.param('q_au_{}'.format(u), self.hyperparams['a_u'],
                              constraint=positive)
            q_bu = pyro.param('q_bu_{}'.format(u), self.hyperparams['b_u'],
                              constraint=positive)
            user_mean_dist = dist.Gamma(q_au, q_bu)
            user_mean = pyro.sample('user_mean_{}'.format(u), user_mean_dist)

            # Sample latents
            for l in pyro.plate('user_latents_loop_{}'.format(u), self.hyperparams['num_latents']):
                q_lu1 = pyro.param('q_lu1_{},{}'.format(u, l), self.hyperparams['c_u'],
                                   constraint=positive)
                q_lu2 = pyro.param('q_lu2_{},{}'.format(u, l), torch.tensor(1.),
                                   constraint=positive)
                user_latents_dist = dist.Gamma(q_lu1, q_lu2)
                user_latents = pyro.sample('user_latents_{},{}'.format(u, l), user_latents_dist)

        for i in pyro.plate('items_loop', self.hyperparams['num_items']):
            # Variational parameters per item
            q_ai = pyro.param('q_ai_{}'.format(i), self.hyperparams['a_i'],
                              constraint=positive)
            q_bi = pyro.param('q_bi_{}'.format(i), self.hyperparams['b_i'],
                              constraint=positive)
            item_mean_dist = dist.Gamma(q_ai, q_bi)
            item_mean = pyro.sample('item_mean_{}'.format(i), item_mean_dist)

            # Sample latents
            for l in pyro.plate('item_latents_loop_{}'.format(i), self.hyperparams['num_latents']):
                q_li1 = pyro.param('q_li1_{},{}'.format(i, l), self.hyperparams['c_u'],
                                   constraint=positive)
                q_li2 = pyro.param('q_li2_{},{}'.format(i, l), torch.tensor(1.),
                                   constraint=positive)
                item_latents_dist = dist.Gamma(q_li1, q_li2)
                item_latents = pyro.sample('item_latents_{},{}'.format(i, l), item_latents_dist)

        ratings_itr = iter(ratings)
        for i in pyro.plate('ratings', self.hyperparams['num_nonmissing']):
            u, i, r = next(ratings_itr)
            q_zu = pyro.param('q_zu_{},{}'.format(u, i), torch.ones(self.hyperparams['num_contexts']),
                              constraint=positive)
            q_zi = pyro.param('q_zi_{},{}'.format(u, i), torch.ones(self.hyperparams['num_contexts']),
                              constraint=positive)
            z_u = pyro.sample('user_context_{},{}'.format(u, i), dist.Categorical(q_zu))
            z_i = pyro.sample('item_context_{},{}'.format(u, i), dist.Categorical(q_zi))

    def fit(self, ratings, num_steps=2000):
        optim = Adam({'lr': 0.1, 'betas': [0.8, 0.99]})
        svi = SVI(self._model, config_enumerate(self._guide, 'sequential'), optim, loss=TraceEnum_ELBO())
        losses = []
        for s in tqdm(range(num_steps)):
            loss = svi.step(ratings)
            losses.append(loss)

        return losses

hyperparams = {}
hyperparams['a_u'] = hyperparams['b_u'] = hyperparams['a_i'] = hyperparams['b_i'] = hyperparams['a_c'] = hyperparams['b_c'] = hyperparams['c_u'] = hyperparams['c_i'] = torch.tensor(1.)
hyperparams['context_conc'] = 5.
hyperparams['num_users'] = 10
hyperparams['num_items'] = 20
hyperparams['num_nonmissing'] = 40
hyperparams['num_latents'] = 4
hyperparams['num_contexts'] = 3
hyperparams['num_context_latents'] = 4
idx = [(u, i) for u in range(10) for i in range(20)]
import random
from torch.distributions import Poisson
random.shuffle(idx)
raw_ratings = Poisson(3.).sample((10, 20))
ratings = [(u, i, raw_ratings[u, i]) for u, i in idx[:40]]
    
mmpf = MMPF(hyperparams)
optim = Adam({'lr': 0.1, 'betas': [0.8, 0.99]})
svi = SVI(mmpf._model, config_enumerate(mmpf._guide, 'sequential'), optim, loss=TraceEnum_ELBO())
losses = []
