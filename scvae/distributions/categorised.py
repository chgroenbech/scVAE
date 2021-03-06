# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#           http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==========================================================================

# ======================================================================== #
#
# Copyright (c) 2017 - 2020 scVAE authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# ======================================================================== #

"""The Categorised distribution class."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow import where
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import tensor_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import check_ops
from tensorflow.python.ops import clip_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import nn_ops
from tensorflow_probability.python.distributions import categorical
from tensorflow_probability.python.distributions import distribution
from tensorflow_probability.python.internal import reparameterization


class Categorised(distribution.Distribution):
    """Categorised distribution.

    The `categorised` object implements batched categorised distributions.
    The categorised model is defined by a `Categorical` distribution (the
    categorised) and a python list of `Distribution` objects.

    Methods supported include `log_prob`, `prob`, `mean`, `sample`, and
    `entropy_lower_bound`.
    """

    def __init__(self,
                 cat,
                 dist,
                 validate_args=False,
                 allow_nan_stats=True,
                 name="Categorised"):
        """Initialise a categorised distribution.

        A `categorised` is defined by a `Categorical` (`cat`, representing the
        categorised probabilities) and a list of `Distribution` objects
        all having matching dtype, batch shape, event shape, and continuity
        properties (the dist).

        The `num_classes` of `cat` must be possible to infer at graph
        construction time and match `len(dist)`.

        Args:
            cat: A `Categorical` distribution instance, representing the
                probabilities of `distributions`.
            dist: A `Distribution` instance.
                The instance must have `batch_shape` matching the
                `Categorical`.
            validate_args: Python `bool`, default `False`. If `True`, raise a
                runtime error if batch or event ranks are inconsistent between
                cat and any of the distributions. This is only checked if the
                ranks cannot be determined statically at graph construction
                time.
            allow_nan_stats: Boolean, default `True`. If `False`, raise an
                exception if a statistic (e.g. mean/mode/etc...) is undefined
                for any batch member. If `True`, batch members with valid
                parameters leading to undefined statistics will return NaN for
                this statistic.
            name: A name for this distribution (optional).

        Raises:
            TypeError: If cat is not a `Categorical`, or `dist` is not
                a list or tuple, or the elements of `dist` are not
                instances of `Distribution`, or do not have matching `dtype`.
            ValueError: If `dist` is an empty list or tuple, or its
                elements do not have a statically known event rank.
                If `cat.num_classes` cannot be inferred at graph creation time,
                or the constant value of `cat.num_classes` is not equal to
                `len(dist)`, or all `dist` and `cat` do not have
                matching static batch shapes, or all dist do not
                have matching static event shapes.
        """
        parameters = locals()
        if not isinstance(cat, categorical.Categorical):
            raise TypeError(
                "cat must be a Categorical distribution, but saw: %s" % cat
            )
        if not dist:
            raise ValueError("dist must be non-empty")

        if not isinstance(dist, distribution.Distribution):
            raise TypeError(
                "dist must be a Distribution instance"
                " but saw: %s" % dist
            )

        dtype = dist.dtype
        static_event_shape = dist.event_shape
        static_batch_shape = cat.batch_shape

        if static_event_shape.ndims is None:
            raise ValueError(
                "Expected to know rank(event_shape) from dist, but "
                "the distribution does not provide a static number of ndims"
            )

        # Ensure that all batch and event ndims are consistent
        with ops.name_scope(name, values=[cat.logits]):
            num_dist = cat.event_size
            self._static_cat_event_size = tensor_util.constant_value(num_dist)
            if self._static_cat_event_size is None:
                raise ValueError(
                    "Could not infer number of classes from cat and unable to "
                    "compare this value to the number of components passed in."
                )
            # Possibly convert from numpy 0-D array
            self._static_cat_event_size = int(self._static_cat_event_size)

            cat_batch_shape = cat.batch_shape_tensor()
            cat_batch_rank = array_ops.size(cat_batch_shape)
            if validate_args:
                dist_batch_shape = dist.batch_shape_tensor()
                dist_batch_rank = array_ops.size(dist_batch_shape)
                check_message = ("dist batch shape must match cat "
                                 "batch shape")
                self._assertions = [check_ops.assert_equal(
                    cat_batch_rank, dist_batch_rank, message=check_message)]
                self._assertions += [
                    check_ops.assert_equal(
                        cat_batch_shape, dist_batch_shape,
                        message=check_message)]
            else:
                self._assertions = []

            self._cat = cat
            self._dist = dist
            self._event_size = self._static_cat_event_size - 1
            self._static_event_shape = static_event_shape
            self._static_batch_shape = static_batch_shape

        # We let the categorised distribution access _graph_parents since its
        # arguably more like a baseclass
        graph_parents = self._cat._graph_parents
        graph_parents += self._dist._graph_parents

        super(Categorised, self).__init__(
            dtype=dtype,
            reparameterization_type=reparameterization.NOT_REPARAMETERIZED,
            validate_args=validate_args,
            allow_nan_stats=allow_nan_stats,
            parameters=parameters,
            graph_parents=graph_parents,
            name=name)

    @property
    def cat(self):
        """Count Categories"""
        return self._cat

    @property
    def dist(self):
        """Distribution, p(x)"""
        return self._dist

    @property
    def event_size(self):
        """Scalar `int32` tensor: the number of categorical classes."""
        return self._event_size

    def _batch_shape_tensor(self):
        return self._cat.batch_shape_tensor()

    def _batch_shape(self):
        return self._static_batch_shape

    def _event_shape_tensor(self):
        return self._dist.event_shape_tensor()

    def _event_shape(self):
        return self._static_event_shape

    def _mean(self):
        with ops.control_dependencies(self._assertions):
            # List of batch tensors for categorical probabilities, pi_k
            cat_probs = self._cat_probs(log_probs=False)
            # Individual contributions to categorical mean: k * pi_k
            cat_means = [k * cat_probs[k] for k in range(self.event_size)]
            # E_cat[x] = \sum^{K-1}_k k * pi_k
            cat_mean = math_ops.add_n(cat_means)

            # Scaled count distribution mean shifted by K:
            # pi_K * (E_dist[x] + K)
            dist_mean = cat_probs[-1] * (self._dist.mean() + self.event_size)

            return cat_mean + dist_mean

    def _variance(self):
        with ops.control_dependencies(self._assertions):
            # List of batch tensors for categorical probabilities, pi_k
            cat_probs = self._cat_probs(log_probs=False)
            # Individual contributions to categorical 2nd moment: k^2 * pi_k
            cat_2nd_moments = [
                k**2 * cat_probs[k] for k in range(self.event_size)]
            # E_cat[x] = \sum^{K-1}_k k^2 * pi_k
            cat_2nd_moment = math_ops.add_n(cat_2nd_moments)

            # Scaled count distribution 2nd moment shifted by K:
            #        pi_K * (2*K*E_dist[x] + V_dist[x] + E_dist[x]^2 + K^2)
            dist_2nd_moment = cat_probs[-1] * (
                2 * self.event_size * self._dist.mean()
                + self._dist.variance()
                + math_ops.square(self._dist.mean())
                + self.event_size**2
            )

            # Variance: V[x] = E
            return (
                cat_2nd_moment
                + dist_2nd_moment
                - math_ops.square(self._mean())
            )

    def _log_prob(self, x):
        with ops.control_dependencies(self._assertions):
            x = ops.convert_to_tensor(x, name="x")
            cat_log_prob = self._cat.log_prob(math_ops.cast(
                clip_ops.clip_by_value(x, 0, self.event_size), dtypes.int32))
            return where(
                x < self.event_size,
                cat_log_prob,
                cat_log_prob + self._dist.log_prob(x - self.event_size)
            )

    def _prob(self, x):
        return math_ops.exp(self._log_prob(x))

    def _cat_probs(self, log_probs):
        """Get a list of num_classes batchwise probabilities."""
        which_softmax = nn_ops.log_softmax if log_probs else nn_ops.softmax
        cat_probs = which_softmax(self.cat.logits)
        cat_probs = array_ops.unstack(
            cat_probs,
            num=self._static_cat_event_size,
            axis=-1
        )
        return cat_probs
