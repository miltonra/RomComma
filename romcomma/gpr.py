#  BSD 3-Clause License.
# 
#  Copyright (c) 2019-2021 Robert A. Milton. All rights reserved.
# 
#  Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
# 
#  1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 
#  2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
# 
#  3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this
#     software without specific prior written permission.
# 
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
#  THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
#  CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
#  PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
#  LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
#  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

""" Contains:

A GPInterface base class - Anyone wishing to implement their own GPs should inherit from this).

A GPFlow implementation of Gaussian Process Regression.
"""

from __future__ import annotations

from abc import abstractmethod
from romcomma.typing_ import *
from romcomma.data import Fold, Frame
from romcomma.base import Parameters, Model
from romcomma. kernels import Kernel
import numpy as np
import gpflow as gf
import romcomma.mogpflow as mf
import tensorflow as tf
from contextlib import suppress


class Likelihood(Model):

    class Parameters(Parameters):
        """ The Parameters set of a GP."""

        @classmethod
        @property
        def Values(cls) -> Type[NamedTuple]:
            """ The NamedTuple underpinning this Parameters set."""

            class Values(NamedTuple):
                """ The parameters set of a GP.

                Attributes:
                    variance (NP.Matrix): An (L,L), (1,L) or (1,1) noise variance matrix. (1,L) represents an (L,L) diagonal matrix.
                    log_marginal (NP.Matrix): A numpy [[float]] used to record the log marginal likelihood. This is an output parameter, not input.
                """
                variance: NP.Matrix = np.atleast_2d(0.9)
                log_marginal: NP.Matrix = np.atleast_2d(1.0)

            return Values

    @classmethod
    @property
    def DEFAULT_OPTIONS(cls) -> Dict[str, Any]:
        return {'variance': True}

    def optimize(self, **kwargs):
        """ Merely set the trainable parameters."""
        if self.params.variance.shape[0] > 1:
            options = self.DEFAULT_OPTIONS | kwargs
            gf.set_trainable(self._parent.implementation[0].likelihood.variance, options['variance'])

    def __init__(self, parent: GPInterface, read_parameters: bool = False, **kwargs: NP.Matrix):
        super().__init__(parent.folder / 'likelihood', read_parameters, **kwargs)
        self._parent = parent


# noinspection PyPep8Naming
class GPInterface(Model):
    """ Interface to a Gaussian Process."""

    class Parameters(Parameters):
        """ The Parameters set of a GP."""

        @classmethod
        @property
        def Values(cls) -> Type[NamedTuple]:
            """ The NamedTuple underpinning this Parameters set."""
            class Values(NamedTuple):
                """ The parameters set of a GP.

                Attributes:
                    kernel (NP.Matrix): A numpy [[str]] identifying the type of Kernel, as returned by gp.kernel.TypeIdentifier(). This is never set externally.
                        The kernel parameter, when provided, must be a ``[[Kernel.Parameters]]`` set storing the desired kernel parameters.
                        The kernel is constructed by inferring its type from the type of Kernel.Parameters.
                """
                kernel: NP.Matrix = np.atleast_2d(None)
            return Values

    @classmethod
    @property
    @abstractmethod
    def DEFAULT_OPTIONS(cls) -> Dict[str, Any]:
        """ Hyper-parameter optimizer options"""

    @classmethod
    @property
    def KERNEL_FOLDER_NAME(cls) -> str:
        """ The name of the folder where kernel parameters are stored."""
        return "kernel"

    @property
    def fold(self) -> Fold:
        """ The parent fold. """
        return self._fold

    @property
    def test_csv(self) -> Path:
        return self._folder / "test.csv"

    @property
    def kernel(self) -> Kernel:
        return self._kernel

    @property
    def likelihood(self) -> Likelihood:
        return self._likelihood

    @property
    @abstractmethod
    def implementation(self) -> Tuple[Any, ...]:
        """ The implementation of this GP in GPFlow.
            If ``noise_variance.shape == (1,L)`` an L-tuple of kernels is returned.
            If ``noise_variance.shape == (L,L)`` a 1-tuple of multi-output kernels is returned.
        """

    @property
    def L(self) -> int:
        """ The output (Y) dimensionality."""
        return self._L

    @property
    def M(self) -> int:
        """ The input (X) dimensionality."""
        return self._M

    @property
    def N(self) -> int:
        """ The the number of training samples."""
        return self._M


    @property
    @abstractmethod
    def X(self) -> Any:
        """ The implementation training inputs."""

    @property
    @abstractmethod
    def Y(self) -> Any:
        """ The implementation training outputs."""

    @property
    @abstractmethod
    def KNoisy_Cho(self) -> Union[NP.Matrix, TF.Tensor]:
        """ The Cholesky decomposition of the LNxLN noisy kernel kernel(X, X) + likelihood.variance. """

    @property
    @abstractmethod
    def KNoisyInv_Y(self) -> Union[NP.Matrix, TF.Tensor]:
        """ The LN-Vector, which pre-multiplied by the LoxLN kernel k(x, X) gives the Lo-Vector predictive mean f(x).
        Returns: ChoSolve(self.KNoisy_Cho, self.Y) """

    @abstractmethod
    def optimize(self, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def predict(self, X: NP.Matrix, y_instead_of_f: bool = True) -> Tuple[NP.Matrix, NP.Matrix]:
        """ Predicts the response to input X.

        Args:
            X: An (o, M) design Matrix of inputs.
            y_instead_of_f: True to include noise in the variance of the result.
        Returns: The distribution of Y or f, as a pair (mean (o, L) Matrix, std (o, L) Matrix).
        """

    def test(self) -> Frame:
        """ Tests the GP on the test data in self._fold.test_data.

        Returns: The test_data results as a Frame backed by GP.test_result_csv.
        """
        result = Frame(self.test_csv, self._fold.test_data.df)
        Y_heading = self._fold.meta['data']['Y_heading']
        prediction = self.predict(self._fold.test_x.values)
        predictive_mean = (result.df.loc[:, [Y_heading]].copy().rename(columns={Y_heading: "Predictive Mean"}, level=0))
        predictive_mean.iloc[:] = prediction[0]
        predictive_std = (result.df.loc[:, [Y_heading]].copy().rename(columns={Y_heading: "Predictive Std"}, level=0))
        predictive_std.iloc[:] = prediction[1]
        predictive_error = (result.df.loc[:, [Y_heading]].copy().rename(columns={Y_heading: "Predictive Error"}, level=0))
        predictive_error.iloc[:] -= predictive_mean.to_numpy(dtype=float, copy=False)
        result.df = result.df.join([predictive_mean, predictive_std, predictive_error])
        result.write()
        return result

    def broadcast_parameters(self, is_independent: bool, is_isotropic: bool, folder: Optional[PathLike] = None) -> GPInterface:
        """ Broadcast the parameters of the GP (including kernels) to higher dimensions.
        Shrinkage raises errors, unchanged dimensions silently do nothing.

        Args:
            is_independent: Whether the outputs will be treated as independent.
            is_isotropic: Whether to restrict the kernel to be isotropic.
            folder: The file location, which is ``self.folder`` if ``folder is None`` (the default).
        Returns: ``self``, for chaining calls.
        """
        target_shape = (1, self._L) if is_independent else (self._L, self._L)
        self._likelihood.parameters.broadcast_value(model_name=self.folder, field="variance", target_shape=target_shape, is_diagonal=is_independent,
                                                    folder=folder)
        self._kernel.broadcast_parameters(variance_shape=target_shape, M=1 if is_isotropic else self._M, folder=folder)
        self._implementation = None
        self._implementation = self.implementation
        return self

    @abstractmethod
    def __init__(self, name: str, fold: Fold, is_read: bool, is_isotropic: bool, is_independent: bool,
                 kernel_parameters: Optional[Kernel.Parameters] = None, **kwargs: NP.Matrix):
        """ Set up parameters, and checks dimensions.

        Args:
            name: The name of this GP.
            fold: The Fold housing this GP.
            is_read: If True, the GP.kernel.parameters and GP.parameters and are read from ``fold.folder/name``, otherwise defaults are used.
            is_independent: Whether the outputs will be treated as independent.
            is_isotropic: Whether to restrict the kernel to be isotropic.
            kernel_parameters: A Kernel.Parameters to use for GP.kernel.parameters. If not None, this replaces the kernel specified by file/defaults.
                If None, the kernel is read from file, or set to the default Kernel.Parameters(), according to read_from_file.
            **kwargs: The GP.parameters fields=values to replace after reading from file/defaults.
        Raises:
            IndexError: If a parameter is mis-shaped.
        """
        self._fold = fold
        self._X, self._Y = self._fold.X.to_numpy(dtype=gf.config.default_float(), copy=True), self._fold.Y.to_numpy(dtype=gf.config.default_float(), copy=True)
        self._N, self._M, self._L = self._fold.N, self._fold.M, self._fold.L
        super().__init__(self._fold.folder / name, is_read, **kwargs)
        self._likelihood = Likelihood(self, is_read, **kwargs)
        if is_read and kernel_parameters is None:
            KernelType = Kernel.TypeFromIdentifier(self.params.kernel[0, 0])
            self._kernel = KernelType(self._folder / self.KERNEL_FOLDER_NAME, is_read)
        else:
            if kernel_parameters is None:
                kernel_parameters = Kernel.Parameters()
            KernelType = Kernel.TypeFromParameters(kernel_parameters)
            self._kernel = KernelType(self._folder / self.KERNEL_FOLDER_NAME, is_read, **kernel_parameters.as_dict())
            self._parameters.replace(kernel=np.atleast_2d(KernelType.TYPE_IDENTIFIER)).write()
        self.broadcast_parameters(is_independent, is_isotropic)


# noinspection PyPep8Naming
class GP(GPInterface):
    """ Implementation of a Gaussian Process."""

    @classmethod
    @property
    def DEFAULT_OPTIONS(cls) -> Dict[str, Any]:
        return {'maxiter': 5000, 'gtol': 1E-16}

    @property
    def implementation(self) -> Tuple[Any, ...]:
        if self._implementation is None:
            if self._likelihood.params.variance.shape[0] == 1:
                self._implementation = tuple(gf.models.GPR(data=(self._X, self._Y[:, [l]]), kernel=kernel, mean_function=None,
                                                            noise_variance=self._likelihood.params.variance[0, l])
                                            for l, kernel in enumerate(self._kernel.implementation))
            else:
                self._implementation = tuple(mf.models.MOGPR(data=(self._X, self._Y), kernel=kernel, mean_function=None,
                                                             noise_variance=self._likelihood.params.variance)
                                             for kernel in self._kernel.implementation)
        return self._implementation

    def optimize(self, method: str = 'L-BFGS-B', **kwargs):
        """ Optimize the GP hyper-parameters.

        Args:
            method: The optimization algorithm (see https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html).
            kwargs: A Dict of implementation-dependent optimizer options, following the format of GPInterface.DEFAULT_OPTIONS.
        """
        options = (self._read_options() if self._options_json.exists() else self.DEFAULT_OPTIONS)
        options.update(kwargs)
        options.pop('result', None)
        kernel_options = options.pop('kernel', {})
        likelihood_options = options.pop('likelihood', {})
        self._kernel.optimize(**kernel_options)
        self._likelihood.optimize(**likelihood_options)
        opt = gf.optimizers.Scipy()
        options.update({'result': str(tuple(opt.minimize(closure=gp.training_loss, variables=gp.trainable_variables, method=method, options=options)
                                                  for gp in self._implementation))})
        self._write_options(options)
        if self._likelihood.params.variance.shape[0] == 1:
            self._likelihood.parameters = self._likelihood.parameters.replace(variance=tuple(gp.likelihood.variance.numpy() for gp in self._implementation),
                                                                              log_marginal=tuple(gp.log_marginal_likelihood() for gp in self._implementation)
                                                                              ).write()
            self._kernel.parameters = self._kernel.parameters.replace(variance=tuple(gp.kernel.variance.numpy() for gp in self._implementation),
                                                                      lengthscales=tuple(gp.kernel.lengthscales.numpy() for gp in self._implementation)
                                                                      ).write()
        else:
            self._likelihood.parameters = self._likelihood.parameters.replace(variance=self._implementation[0].likelihood.variance.value.numpy(),
                                                                              log_marginal=self._implementation[0].log_marginal_likelihood().numpy()
                                                                              ).write()
            self._kernel.parameters = self._kernel.parameters.replace(variance=self._implementation[0].kernel.variance.value.numpy(),
                                                                      lengthscales=tf.squeeze(self._implementation[0].kernel.lengthscales),
                                                                      ).write()

    def predict(self, X: NP.Matrix, y_instead_of_f: bool = True) -> Tuple[NP.Matrix, NP.Matrix]:
        X = X.astype(dtype=gf.config.default_float())
        if self._likelihood.params.variance.shape[0] == 1:
            results = tuple(gp.predict_y(X) if y_instead_of_f else gp.predict_f(X) for gp in self._implementation)
            results = tuple(np.transpose(result) for result in zip(*results))
            results = tuple(results[i][0] for i in range(len(results)))
        else:
            gp = self.implementation[0]
            results = gp.predict_y(X) if y_instead_of_f else gp.predict_f(X)
        return np.atleast_2d(results[0]), np.atleast_2d(np.sqrt(results[1]))

    @property
    def X(self) -> TF.Matrix:
        """ The implementation training inputs as an (N,M) design matrix."""
        return self._implementation[0].data[0]

    @property
    def Y(self) -> TF.Matrix:
        """ The implementation training outputs as an (N,L) design matrix. """
        return self._implementation[0].data[1]

    @property
    def KNoisy_Cho(self) -> TF.Tensor:
        if self._likelihood.params.variance.shape[0] == 1:
            result = np.zeros(shape=(self._L * self._N, self._L * self._N))
            for l, gp in enumerate(self._implementation):
                K = gp.kernel(self.X)
                K_diag = tf.linalg.diag_part(K)
                result[l*self._N:(l+1)*self._N, l*self._N:(l+1)*self._N] = tf.linalg.set_diag(K, K_diag + tf.fill(tf.shape(K_diag), gp.likelihood.variance))
        else:
            gp = self._implementation[0]
            result = gp.likelihood.add_to(gp.KXX)
        return tf.linalg.cholesky(result)

    @property
    def KNoisyInv_Y(self) -> TF.Tensor:
        if self._likelihood.params.variance.shape[0] == 1:
            Y = np.reshape(self._Y.transpose().flatten(), [-1, 1])
        else:
            Y = tf.reshape(tf.transpose(self.Y), [-1, 1])
        return tf.linalg.cholesky_solve(self.KNoisy_Cho, Y)

    def check_KNoisyInv_Y(self, x: NP.Matrix, y: NP.Matrix) -> NP.Matrix:
        """ FOR TESTING PURPOSES ONLY. Should return 0 Vector (to within numerical error tolerance).

        Args:
            x: An (o, M) matrix of inputs.
            y: An (o, L) matrix of outputs.
        Returns: Should return zeros((Lo)) (to within numerical error tolerance)

        """
        o = x.shape[0]
        if self._likelihood.params.variance.shape[0] == 1:
            kernel = np.zeros(shape=(self._L * o, self._L * self._N))
            for l, gp in enumerate(self._implementation):
                X = gp.data[0]
                kernel[l*o:(l+1)*o, l*self._N:(l+1)*self._N] = gp.kernel(x, X)
        else:
            gp = self._implementation[0]
            kernel = gp.kernel(x, self.X)
        predicted = self.predict(x)[0]
        print(np.sqrt(np.sum((y-predicted)**2)/o))
        result = tf.transpose(tf.reshape(tf.einsum('on, ni -> o', kernel, self.KNoisyInv_Y), (-1, o)))
        result = result - predicted
        return np.sqrt(np.sum(result * result)/o)

    def __init__(self, name: str, fold: Fold, is_read: bool, is_isotropic: bool, is_independent: bool,
                 kernel_parameters: Optional[Kernel.Parameters] = None, **kwargs: NP.Matrix):
        """ GP Constructor. Calls __init__ to setup parameters, then checks dimensions.

        Args:
            name: The name of this GP.
            fold: The Fold housing this GP.
            is_read: If True, the GP.kernel.parameters and GP.parameters and are read from ``fold.folder/name``, otherwise defaults are used.
            is_independent: Whether the outputs will be treated as independent.
            is_isotropic: Whether to restrict the kernel to be isotropic.
            kernel_parameters: A Kernel.Parameters to use for GP.kernel.parameters. If not None, this replaces the kernel specified by file/defaults.
                If None, the kernel is read from file, or set to the default Kernel.Parameters(), according to read_from_file.
            **kwargs: The GP.parameters fields=values to replace after reading from file/defaults.
        Raises:
            IndexError: If a parameter is mis-shaped.
        """
        super().__init__(name, fold, is_read, is_isotropic, is_independent, kernel_parameters, **kwargs)
