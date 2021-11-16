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

""" Contains data storage structures."""

from __future__ import annotations

from romcomma.typing_ import *
from copy import deepcopy
import itertools
import random
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
from enum import IntEnum, auto
import scipy.stats
import json


class Frame:
    """ Encapsulates a pd.DataFrame (df) backed by a source file."""
    @classmethod
    @property
    def DEFAULT_CSV_OPTIONS(cls) -> Dict[str, Any]:
        """ The default options (kwargs) to pass to pandas.pd.read_csv."""
        return {'sep': ',', 'header': [0, 1], 'index_col': 0, }

    @property
    def csv(self) -> Path:
        """ The csv file."""
        return self._csv

    @property
    def is_empty(self) -> bool:
        """ Defines the empty Frame as that having an empty Path."""
        return 0 == len(self._csv.parts)

    def write(self):
        """ Write to csv, according to Frame.DEFAULT_CSV_OPTIONS."""
        assert not self.is_empty, 'Cannot write when frame.is_empty.'
        self.df.to_csv(path_or_buf=self._csv, sep=Frame.DEFAULT_CSV_OPTIONS['sep'], index=True)

    # noinspection PyDefaultArgument
    def __init__(self, csv: PathLike = Path(), df: pd.DataFrame = pd.DataFrame(), **kwargs):
        """ Initialize Frame.

        Args:
            csv: The csv file.
            df: The initial data. If this is empty, it is read from csv, otherwise it overwrites (or creates) csv.
        Keyword Args:
            kwargs: Updates Frame.DEFAULT_CSV_OPTIONS for csv reading as detailed in
                https://pandas.pydata.org/pandas-docs/stable/generated/pandas.read_csv.html.
                This is not relevant to writing, which just uses Frame.DEFAULT_CSV_OPTIONS.
        """
        self._csv = Path(csv)
        if self.is_empty:
            assert df.empty, 'csv is an empty path, but df is not an empty pd.DataFrame.'
            self.df = df
        elif df.empty:
            self.df = pd.read_csv(self._csv, **{**Frame.DEFAULT_CSV_OPTIONS, **kwargs})
        else:
            self.df = df
            self.write()


class Store:
    """ A ``store`` object is defined as a ``store.folder`` containing a ``store.csv`` file and a ``store._meta_json`` file.

    These files specify the global dataset to be analyzed. This dataset must be further split into Folds contained within the Store.
    """

    @property
    def folder(self) -> Path:
        """ The Store folder."""
        return self._folder

    @property
    def data(self) -> Frame:
        """ The Store data."""
        return self._data

    @property
    def X(self) -> pd.DataFrame:
        """ The input X, as an (N,M) design Matrix with column headings."""
        return self._data.df[self._meta['data']['X_heading']]

    @property
    def Y(self) -> pd.DataFrame:
        """ The output Y as an (N,L) Matrix with column headings."""
        return self._data.df[self._meta['data']['Y_heading']]

    def _read_meta_json(self) -> dict:
        with open(self._meta_json, mode='r') as file:
            return json.load(file)

    def _write_meta_json(self):
        with open(self._meta_json, mode='w') as file:
            json.dump(self._meta, file, indent=8)

    @property
    def meta(self) -> dict:
        """ The Store metadata."""
        return self._meta

    def meta_update(self):
        """ Update __meta__"""
        self._meta.update({'data': {'X_heading': self._data.df.columns.values[0][0],
                                    'Y_heading': self._data.df.columns.values[-1][0]}})
        self._meta['data'].update({'N': self.data.df.shape[0], 'M': self.X.shape[1],
                                   'L': self.Y.shape[1]})
        self._write_meta_json()

    @property
    def N(self) -> int:
        """ The number of datapoints (rows of data)."""
        return self._meta['data']['N']

    @property
    def M(self) -> int:
        """ The number of input columns in `self.data`."""
        return self._meta['data']['M']

    @property
    def L(self) -> int:
        """ The number of output columns in `self.data`."""
        return self._meta['data']['L']

    @property
    def K(self) -> int:
        """ The number of folds contained in this Store."""
        return self._meta['K']

    def into_K_folds(self, K: int, shuffle_before_folding: bool = False, normalization: Optional[PathLike] = None) -> int:
        """ Fold this store into K Folds, indexed by range(K).
        An additional Fold, indexed by K, takes all the store data for both training and (invalid) testing.
        To avoid duplication, when K=1 there is no fold.0, as this would be identical to fold.1.

        Args:
            K: The number of Folds, between 1 and N inclusive.
            shuffle_before_folding: Whether to shuffle the data before sampling.
            normalization: An optional __normalization__.csv file to use.

        Raises:
            IndexError: Unless 1 &lt= K &lt= N.
        """
        data = self.data.df
        N = data.shape[0]
        if not (1 <= K <= N):
            raise IndexError(f'K={K:d} does not lie between 1 and N={N:d} inclusive.')

        for k in range(K + 1, self.K + 1):
            shutil.rmtree(self.fold_folder(k))

        self._meta.update({'K': K, 'shuffle before folding': shuffle_before_folding})
        self._write_meta_json()

        index = list(range(N))
        if shuffle_before_folding:
            random.shuffle(index)

        if K > 1:
            K_blocks = [list(range(K)) for dummy in range(int(N / K))]
            K_blocks.append(list(range(N % K)))
            for K_range in K_blocks:
                random.shuffle(K_range)
            indicator = list(itertools.chain(*K_blocks))

            for k in range(K):
                indicated = tuple(zip(index, indicator))
                data_index = [index for index, indicator in indicated if k != indicator]
                test_index = [index for index, indicator in indicated if k == indicator]
                Fold.from_dfs(parent=self, k=k, data=data.iloc[data_index], test_data=data.iloc[test_index], normalization=normalization)

        Fold.from_dfs(parent=self, k=K, data=data.iloc[index], test_data=data.iloc[index], normalization=normalization)
        return K

    def fold_folder(self, k: int) -> Path:
        """ Returns the path containing each fold between 0 and K.

        Args:
            k: The fold which the function is creating the path for.
        """
        return self.folder / f'fold.{k:d}'

    def Y_split(self):
        """Split this Store into L Y_splits. Each Y.l is just a Store containing the lth output only.

        Raises:
            TypeError: if self is a Fold.
        """
        if isinstance(self, Fold):
            raise TypeError('Cannot Y_split a Fold, only a Store.')
        for l in range(self.L):
            destination = self.folder / f'Y.{l:d}'
            if not destination.exists():
                destination.mkdir(mode=0o777, parents=True, exist_ok=False)
            indices = np.append(range(self.M), self.M + l)
            data = self.data.df.take(indices, axis=1, is_copy=True)
            Frame(destination / self._csv.name, data)
            meta = deepcopy(self._meta)
            meta['data']['L'] = 1
            Store.from_df(destination, data, meta)

    @property
    def Y_splits(self) -> List[Tuple[int, Path]]:
        """ Lists the index and path of every Y_split in this Store."""
        return [(int(Y_dir.suffix[1:]), Y_dir) for Y_dir in self.folder.glob('Y.[0-9]*')]

    class _InitMode(IntEnum):
        READ_META_ONLY = auto()
        READ = auto()
        CREATE = auto()

    def __init__(self, folder: PathLike, **kwargs):
        """ Initialize Store.

        Args:
            folder: The location (folder) of the Store.
        """
        self._folder = Path(folder)
        self._meta_json = self._folder / '__meta__.json'
        self._X_rotation = self._folder / '__X_rotation__.csv'
        self._csv = self._folder / '__data__.csv'
        self._data = None
        init_mode = kwargs.get('init_mode', Store._InitMode.READ)
        if init_mode <= Store._InitMode.READ:
            self._meta = self._read_meta_json()
            if init_mode is Store._InitMode.READ:
                self._data = Frame(self._csv)
        else:
            self._folder.mkdir(mode=0o777, parents=True, exist_ok=True)

    @classmethod
    @property
    def DEFAULT_META(cls) -> Dict[str, Any]:
        """ Default meta data for a store."""
        return {'csv_kwargs': Frame.DEFAULT_CSV_OPTIONS, 'data': {}, 'K': 0, 'shuffle before folding': False}

    @classmethod
    @property
    def DEFAULT_CSV_OPTIONS(cls) -> Dict[str, Any]:
        """ The default options (kwargs) to pass to pandas.read_csv."""
        return {'skiprows': None, 'index_col': None}

    @classmethod
    def from_df(cls, folder: PathLike, df: pd.DataFrame, meta: Dict = DEFAULT_META) -> Store:
        """ Create a Store from a pd.DataFrame.

        Args:
            folder: The location (folder) of the Store.
            df: The data to store in [Return].csv.
            meta: The meta data to store in [Return]._meta_json.
        Returns: A new Store.
        """
        store = Store(folder, init_mode=Store._InitMode.CREATE)
        store._meta = cls.DEFAULT_META | meta
        store._data = Frame(store._csv, df)
        store.meta_update()
        return store

    @classmethod
    def from_csv(cls, folder: PathLike, csv: PathLike, meta: Dict = DEFAULT_META, skiprows: ZeroOrMoreInts = None, **kwargs) -> Store:
        """ Create a Store from a csv file.

        Args:
            folder: The location (folder) of the target Store.
            csv: The file containing the data to store in [Return].csv.
            meta: The meta data to store in [Return]._meta_json.
            skiprows: The rows of csv to skip while reading, a convenience update to csv_kwargs.
        Keyword Args:
            kwargs: Updates Store.DEFAULT_CSV_OPTIONS for reading the csv file, as detailed in
                https://pandas.pydata.org/pandas-docs/stable/generated/pandas.pd.read_csv.html.
        Returns: A new Store located in folder.
        """
        csv = Path(csv)
        origin_csv_kwargs = {**cls.DEFAULT_CSV_OPTIONS, **kwargs, **{'skiprows': skiprows}}
        data = Frame(csv, **origin_csv_kwargs)
        meta['origin'] = {'csv': str(csv.absolute()), 'origin_csv_kwargs': origin_csv_kwargs}
        return cls.from_df(folder, data.df, meta)


class Fold(Store):
    """ A Fold is defined as a folder containing a ``__data__.csv``, a ``__meta__.json`` file and a ``__test__.csv`` file.
    A Fold is a Store equipped with a test_data pd.DataFrame backed by ``__test__.csv``.

    Additionally, a fold can reduce the dimensionality ``M`` of the input ``X``.
    """

    @property
    def normalization(self) -> Normalization:
        return self._normalization

    @property
    def test_csv(self) -> Path:
        """ The test_data data file. Must be identical in format to the self.csv file."""
        return self.folder / '__test__.csv'

    @property
    def test_data(self) -> Frame:
        """ The test_data data."""
        return self._test_data

    @property
    def test_x(self) -> pd.DataFrame:
        """ The test_data input x, as an (n,M) design Matrix with column headings."""
        return self._test_data.df[self._meta['data']['X_heading']]

    @property
    def test_y(self) -> pd.DataFrame:
        """ The test_data output y as an (n,L) Matrix with column headings."""
        return self._test_data.df[self._meta['data']['Y_heading']]

    @property
    def X_rotation(self) -> NP.Matrix:
        return Frame(self._X_rotation, header=[0]).df.values if self._X_rotation.exists() else np.eye(self.M)

    @X_rotation.setter
    def X_rotation(self, value: NP.Matrix):
        self._data.df.iloc[:, :self.M] = np.einsum('Nm,mM->NM', self._data.df.iloc[:, :self.M], value)
        self._data.write()
        old_value = self.X_rotation
        Frame(self._X_rotation, pd.DataFrame(np.matmul(old_value, value)))

    def __init__(self, parent: Store, k: int, **kwargs):
        """ Initialize Fold by reading existing files. Creation is handled by the classmethod Fold.from_dfs.

        Args:
            parent: The parent Store.
            k: The index of the Fold within parent.
            M: The number of input columns used. If not 0 &lt M &lt self.M, all columns are used.
        """
        init_mode = kwargs.get('init_mode', Store._InitMode.READ)
        assert 0 <= k <= parent.K, f'Fold k={k:d} is out of bounds 0 <= k <= K = {self.K:d} in data.Store({parent.folder:s}'
        super().__init__(parent.fold_folder(k), init_mode=init_mode)
        if init_mode == Store._InitMode.READ:
            self._test_data = Frame(self.test_csv)
            self._normalization = Normalization(self)

    @classmethod
    def from_dfs(cls, parent: Store, k: int, data: pd.DataFrame, test_data: pd.DataFrame,
                 normalization: Optional[PathLike] = None) -> Fold:
        """ Create a Fold from a pd.DataFrame.

        Args:
            parent: The parent Store.
            k: The index of the fold to be created.
            data: Training data.
            test_data: Test data.
            normalization: An optional __normalization__.csv file to use.

        Returns: The Fold created.
        """

        fold = cls(parent, k, init_mode=Store._InitMode.CREATE)
        fold._meta = cls.DEFAULT_META | parent.meta | {'k': k}
        if normalization is None:
            fold._normalization = Normalization(fold, data)
        else:
            fold._normalization = Normalization(fold)
            shutil.copy(Path(normalization), fold._normalization.csv)
        fold._data = Frame(fold._csv, fold.normalization.apply_to(data))
        fold._test_data = Frame(fold.test_csv, fold.normalization.apply_to(test_data))
        fold.meta_update()
        return fold


class Normalization:
    """ Encapsulates the normalization of data.
        X data is assumed to follow a Uniform distribution, which is normalized to U[0,1] , then inverse probability transformed to N[0,1].
        Y data is normalized to zero mean and unit variance.
    """
    @classmethod
    @property
    def UNIFORM_MARGIN(cls) -> float:
        return 1.0E-12

    @property
    def csv(self) -> Path:
        return self._fold.folder / '__normalization__.csv'

    @property
    def frame(self) -> Frame:
        """ The normalization frame."""
        self._frame = Frame(self.csv) if self._frame is None else self._frame
        return self._frame

    @property
    def _relevant_stats(self) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        return (self.frame.df.iloc[self.frame.df.index.get_loc('min'), :self._fold.M], self.frame.df.iloc[self.frame.df.index.get_loc('rng'), :self._fold.M],
                self.frame.df.iloc[self.frame.df.index.get_loc('mean'), self._fold.M:], self.frame.df.iloc[self.frame.df.index.get_loc('std'), self._fold.M:])

    def apply_to(self, df: pd.DataFrame) -> pd.DataFrame:
        """ Apply this normalization.

        Args:
            df: The pd.DataFrame to Normalize.

        Returns: df, Normalized.
        """
<<<<<<< HEAD
        X_heading = self._fold.meta['data']['X_heading']
        Y_heading = self._fold.meta['data']['Y_heading']
        df.iloc[:, self._fold.M] = df.iloc[:, self._fold.M].sub(self.frame.df.loc['max', X_heading], axis=1)
        df[X_heading] = df.loc[:, X_heading].sub(self.frame.df.loc['min', X_heading], axis=1).div(self.frame.df.loc['rng', X_heading], axis=1)
        df[X_heading] = df.loc[:, X_heading].clip(lower=self.UNIFORM_MARGIN, upper=1-self.UNIFORM_MARGIN)
        df[X_heading] = scipy.stats.norm.ppf(df.loc[:, X_heading], loc=0, scale=1)
        df[Y_heading] = df.loc[:, Y_heading].sub(self.frame.df.loc['mean', Y_heading], axis=1).div(self.frame.df.loc['std', Y_heading], axis=1)

        return df
=======
        X_min, X_rng, Y_mean, Y_std = self._relevant_stats
        X = df.iloc[:, :self._fold.M]
        Y = df.iloc[:, self._fold.M:]
        X = X.sub(X_min, axis=1).div(X_rng, axis=1).clip(lower=self.UNIFORM_MARGIN, upper=1-self.UNIFORM_MARGIN)
        X.iloc[:, :] = scipy.stats.norm.ppf(X, loc=0, scale=1)
        Y = Y.sub(Y_mean, axis=1).div(Y_std, axis=1)
        return pd.concat((X, Y), axis=1)
>>>>>>> 52ea540 (doc)

    def undo_from(self, df: pd.DataFrame) -> pd.DataFrame:
        """ Undo this normalization.

        Args:
            df: The (Normalized) pd.DataFrame to UnNormalize.

        Returns: df, UnNormalized.
        """
        X_min, X_rng, Y_mean, Y_std = self._relevant_stats
        X = df.iloc[:, :self._fold.M]
        Y = df.iloc[:, self._fold.M:]
        X.iloc[:, :] = scipy.stats.norm.cdf(X, loc=0, scale=1)
        X = X.mul(X_rng, axis=1).add(X_min, axis=1)
        Y = Y.mul(Y_std, axis=1).add(Y_mean, axis=1)
        return pd.concat((X, Y), axis=1)

    def __init__(self, fold: Fold, data: Optional[pd.DataFrame] = None):
        """ Initialize this Normalization. If the fold has already been Normalized, that Normalization is returned.

        Args:
            fold: The fold to Normalize.
            data: The data from which to calculate Normalization.
        """
        self._fold = fold
        if self.csv.exists():
            self._frame = Frame(self.csv)
        elif data is None:
            self._frame = None
        else:
            mean = data.mean()
            mean.name = 'mean'
            std = data.std()
            std.name = 'std'
            semi_range = std * np.sqrt(3)
            semi_range.name = 'rng'
            m_min = mean - semi_range
            m_min.name = 'min'
            m_max = mean + semi_range
            m_max.name = 'max'
            df = pd.concat((mean, std, 2 * semi_range, m_min, m_max), axis=1)
            self._frame = Frame(self.csv, df.T)
