#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""problem.py: contains base class for all problems"""
__author__ = "Tomasz Kornuta & Vincent Marois"

import collections
import torch
from torch.utils.data import Dataset
from torch.utils.data.dataloader import default_collate

from utils.app_state import AppState

import logging
logger = logging.Logger('DataDict')


class DataDict(collections.MutableMapping):
    """
    - Mapping: A container object that supports arbitrary key lookups and implements the methods ``__getitem__``, \
    ``__iter__`` and ``__len__``.

    - Mutable objects can change their value but keep their id() -> ease modifying existing keys' value.

    DataDict: Dict used for storing batches of data by problems.

    **This is the main object class used to share data between a problem class and a model class through a worker.**
    """

    def __init__(self, *args, **kwargs):
        """
        DataDict constructor. Can be initialized in different ways:

            >>> data_dict = DataDict()
            >>> data_dict = DataDict({'inputs': torch.tensor(), 'targets': numpy.ndarray()})
            >>> # etc.

        :param args: Used to pass a non-keyworded, variable-length argument list.

        :param kwargs: Used to pass a keyworded, variable-length argument list.
        """
        self.__dict__.update(*args, **kwargs)

    def __setitem__(self, key, value, addkey=False):
        """
        key:value setter function.

        :param key: Dict Key.

        :param value: Associated value.

        :param addkey: Indicate whether or not it is authorized to add a new key `on-the-fly`.\
        Default: ``False``.
        :type addkey: bool

        .. warning::

            `addkey` is set to ``False`` by default as setting it to ``True`` removes flexibility of the\
            ``DataDict``. Indeed, there are some cases where adding a key `on-the-fly` to a ``DataDict`` is\
            useful (e.g. for plotting pre-processing).


        """
        if addkey and key not in self.keys():
            logger.error('KeyError: Cannot modify a non-existing key.')
            raise KeyError('Cannot modify a non-existing key.')
        else:
            self.__dict__[key] = value

    def __getitem__(self, key):
        """
        Value getter function.

        :param key: Dict Key.

        :return: Associated Value.

        """
        return self.__dict__[key]

    def __delitem__(self, key, override=False):
        """
        Delete a key:value pair.

        .. warning::

            By default, it is not authorized to delete an existing key. Set `override` to ``True`` to ignore this\
            restriction.

        :param key: Dict Key.

        :param override: Indicate whether or not to lift the ban of non-deletion of any key.
        :type override: bool

        """
        if not override:
            logger.error('KeyError: Not authorizing the deletion of a key.')
            raise KeyError('Not authorizing the deletion of a key.')
        else:
            del self.__dict__[key]

    def __iter__(self):
        return iter(self.__dict__)

    def __len__(self):
        return len(self.__dict__)

    def __str__(self):
        """
        :return: A simple Dict representation of ``DataDict``.

        """
        return str(self.__dict__)

    def __repr__(self):
        """
        :return: Echoes class, id, & reproducible representation in the Read–Eval–Print Loop.

        """
        return '{}, DataDict({})'.format(super(DataDict, self).__repr__(), self.__dict__)

    def numpy(self):
        """
        Converts the DataDict to numpy objects.

        .. note::

            The ``torch.tensor`` (s) contained in `self` are converted using ``torch.Tensor.numpy()`` : \
            This tensor and the returned ndarray share the same underlying storage. \
            Changes to ``self`` tensor will be reflected in the ndarray and vice versa.

            If an element of ``self`` is not a ``torch.tensor``, it is returned as is.


        :return: Converted DataDict.

        """
        numpy_datadict = self.__class__({key: None for key in self.keys()})

        for key in self:
            if isinstance(self[key], torch.Tensor):
                numpy_datadict[key] = self[key].numpy()
            else:
                numpy_datadict[key] = self[key]

        return numpy_datadict

    def cpu(self):
        """
        Moves the DataDict to memory accessible to the CPU.

        .. note::

            The ``torch.tensor`` (s) contained in `self` are converted using ``torch.Tensor.cpu()`` .
            If an element of `self` is not a ``torch.tensor``, it is returned as is, \
            i.e. We only move the ``torch.tensor`` (s) contained in `self`.


        :return: Converted DataDict.

        """
        cpu_datadict = self.__class__({key: None for key in self.keys()})

        for key in self:
            if isinstance(self[key], torch.Tensor):
                cpu_datadict[key] = self[key].cpu()
            else:
                cpu_datadict[key] = self[key]

        return cpu_datadict

    def cuda(self, device=None, non_blocking=False):
        """
        Returns a copy of this object in CUDA memory.

        .. note::

            Wraps call to ``torch.Tensor.cuda()``: If this object is already in CUDA memory and on the correct device, \
            then no copy is performed and the original object is returned.
            If an element of `self` is not a ``torch.tensor``, it is returned as is, \
            i.e. We only move the ``torch.tensor`` (s) contained in `self`. \


        :param device: The destination GPU device. Defaults to the current CUDA device.
        :type device: torch.device

        :param non_blocking: If True and the source is in pinned memory, the copy will be asynchronous with respect to \
        the host. Otherwise, the argument has no effect. Default: ``False``.
        :type non_blocking: bool

        """
        cuda_datadict = self.__class__({key: None for key in self.keys()})
        for key in self:
            if isinstance(self[key], torch.Tensor):
                cuda_datadict[key] = self[key].cuda(device=device, non_blocking=non_blocking)
            else:
                cuda_datadict[key] = self[key]

        return cuda_datadict

    def detach(self):
        """
        Returns a new DataDict, detached from the current graph.
        The result will never require gradient.

        .. note::
            Wraps call to ``torch.Tensor.detach()`` : the ``torch.tensor`` (s) in the returned ``DataDict`` use the same\
            data tensor(s) as the original one(s).
            In-place modifications on either of them will be seen, and may trigger errors in correctness checks.

        """
        detached_datadict = self.__class__({key: None for key in self.keys()})
        for key in self:
            if isinstance(self[key], torch.Tensor):
                detached_datadict[key] = self[key].detach()
            else:
                detached_datadict[key] = self[key]

        return detached_datadict


class Problem(Dataset):
    """
    Class representing base class for all Problems.

    Inherits from torch.utils.data.Dataset as all subclasses will represent a problem with an associated dataset,\
    and the `worker` will use ``torch.utils.data.dataloader.DataLoader`` to generate batches.

    Implements features & attributes used by all subclasses.

    """

    def __init__(self, params):
        """
        Initializes problem object.

        :param params: Dictionary of parameters (read from the configuration ``.yaml`` file).

        This constructor:

        - stores a pointer to ``params``:

            >>> self.params = params

        - sets a default loss function:

            >>> self.loss_function = None

        - initializes the size of the dataset:

            >>> self.length = None

        - sets a default problem name:

            >>> self.name = 'Problem'

        - initializes the logger.

            >>> self.logger = logging.Logger(self.name)

        - initializes the data definitions: this is used for defining the ``DataDict`` keys.

        .. note::

            This dict contains information about the DataDict produced by the current problem class.

            This object will be used during handshaking between the model and the problem class to ensure that the model
            can accept the batches produced by the problem.

            This dict should at least contains the `targets` field:

                >>> self.data_definitions = {'targets': {'size': [-1, 1], 'type': [torch.Tensor]}}

        - initializes the default values: this is used to pass missing parameters values to the model.

        .. note::

            It is likely to encounter a case where the model needs a parameter value only known when the problem has been
            instantiated, like the size of a vocabulary set or the number of marker bits.

            The user can fill in those values in this dict, which will be passed to the model in its  `__init__`  . The
            model will then be able to fill it its missing parameters values, either from params or this dict.

                >>> self.default_values = {}

        - sets the access to ``AppState``: for dtype, visualization flag etc.

            >>> self.app_state = AppState()

        """
        # Store pointer to params.
        self.params = params

        # Set default loss function.
        self.loss_function = None

        # Size of the dataset
        self.length = None

        # "Default" problem name.
        self.name = 'Problem'

        # initialize the logger.
        self.logger = logging.Logger(self.name)

        # data_definitions: this is used for defining the DataDict keys.

        # This dict contains information about the DataDict produced by the current problem class.
        # This object will be used during handshaking between the model and the problem class to ensure that the model
        # can accept the batches produced by the problem.
        # This dict should at least contains the `targets` field.
        self.data_definitions = {'targets': {'size': [-1, 1], 'type': [torch.Tensor]}}

        # default_values: this is used to pass missing parameters values to the model.

        # It is likely to encounter a case where the model needs a parameter value only known when the problem has been
        # instantiated, like the size of a vocabulary set or the number of marker bits.
        # The user can fill in those values in this dict, which will be passed to the model in its  `__init__`  . The
        # model will then be able to fill it its missing parameters values, either from params or this dict.
        self.default_values = {}

        # Get access to AppState: for dtype, visualization flag etc.
        self.app_state = AppState()

    def __len__(self):
        """
        :return: The size of the dataset.

        """
        return self.length

    def set_loss_function(self, loss_function):
        """
        Sets loss function.

        :param loss_function: Loss function (e.g. nn.CrossEntropyLoss()) that will be set as the optimization criterion.
        """
        self.loss_function = loss_function

    def collate_fn(self, batch):
        """
        Generates a batch of samples from a list of individuals samples retrieved by ``__getitem__``.

        The default collate_fn is ``torch.utils.data.default_collate``.

        .. note::

            This base ``collate_fn`` method only calls the default ``torch.utils.data.default_collate``\
            , as it can handle several cases (mainly tensors, numbers, dicts and lists).

            If your dataset can yield variable-length samples within a batch, or generate batches `on-the-fly`\
            , or possesses another ''non regular'' characteristic, it is most likely that you will need to \
            override this default ``collate_fn``.


        :param batch: Should be a list of DataDict retrieved by `__getitem__`, each containing tensors, numbers,\
        dicts or lists.

        :return: DataDict containing the created batch.

        """
        return default_collate(batch)

    def __getitem__(self, index):
        """
        Getter that returns an individual sample from the problem's associated dataset (that can be generated \
        `on-the-fly`, or retrieved from disk. It can also possibly be composed of several files.).

        .. note::

            **To be redefined in subclasses.**


        .. note::

            **The getter should return a DataDict: its keys should be defined by** ``self.data_definitions`` **keys.**

            This ensures consistency of the content of the ``DataDict`` when processing to the ``handshake``\
            between the ``Problem`` class and the ``Model`` class. For more information, please see\
             ``models.model.Model.handshake_definitions``.

            e.g.:

                >>> data_dict = DataDict({key: None for key in self.data_definitions.keys()})
                >>> # you can now access each value by its key and assign the corresponding object (e.g. `torch.tensor` etc)
                >>> ...
                >>> return data_dict



        .. warning::

            `Mi-Prometheus` supports multiprocessing for data loading (through the use of\
             ``torch.utils.data.dataloader.DataLoader``).

            To construct a batch (say 64 samples), the indexes are distributed among several workers (say 4, so that
            each worker has 16 samples to retrieve). It is best that samples can be accessed individually in the dataset
            folder so that there is no mutual exclusion between the workers and the performance is not degraded.

            If each sample is generated `on-the-fly`, this shouldn't cause a problem. There may be an issue with \
            randomness. Please refer to the official Pytorch documentation for this.


        :param index: index of the sample to return.
        :type index: int

        :return: Empty ``DataDict``, having the same key as ``self.data_definitions``.

        """
        return DataDict({key: None for key in self.data_definitions.keys()})

    def worker_init_fn(self, worker_id):
        """
        Function to be called by ``torch.utils.data.dataloader.DataLoader`` on each worker subprocess, \
        after seeding and before data loading. (default: ``None``).

        .. note::

            The user may need this function to ensure, e.g, that each worker has its own ``NumPy`` random seed.


        :param worker_id: the worker id (in [0, ``torch.utils.data.dataloader.DataLoader.num_workers`` - 1])
        :type worker_id: int

        :return: ``None`` by default
        """
        return None

    def get_data_definitions(self):
        """
        Getter for the data_definitions dict so that it can be accessed by a ``worker`` to establish handshaking with
        the ``Model`` class.

        :return: self.data_definitions()

        """
        return self.data_definitions

    def evaluate_loss(self, data_dict, logits):
        """
        Calculates loss between the predictions/logits and targets (from data_dict) using the selected loss function.

        :param data_dict: DataDict containing (among others) inputs and targets.
        :type data_dict: DataDict

        :param logits: Predictions of the model.

        :return: Loss.
        """

        # Compute loss using the provided loss function. 
        loss = self.loss_function(logits, data_dict['targets'])

        return loss

    def add_statistics(self, stat_col):
        """
        Adds statistics to ``StatisticsCollector``.

        .. note::


            Empty - To be redefined in inheriting classes.


        :param stat_col: ``StatisticsCollector``.

        """
        pass
        
    def collect_statistics(self, stat_col, data_dict, logits):
        """
        Base statistics collection.

         .. note::


            Empty - To be redefined in inheriting classes. The user has to ensure that the corresponding entry \
            in the ``StatisticsCollector`` has been created with ``self.add_statistics()`` beforehand.

        :param stat_col: ``StatisticsCollector``.

        :param data_dict: ``DataDict`` containing inputs and targets.
        :type data_dict: DataDict

        :param logits: Predictions being output of the model.

        """
        pass

    def get_epoch_size(self):
        """
        Compute the number of iterations ('episodes') to run given the size of the dataset and the batch size to cover
        the entire dataset once.

        .. note::

            We are counting the last batch, even though it might be smaller than the other ones if the size of the \
            dataset is not divisible by the batch size. -> Corresponds to ``drop_last=False`` in ``DataLoader()``.

        :return: Number of iterations to perform to go though the entire dataset once.

        """
        if (self.length % self.params['batch_size']) == 0:
            return self.length // self.params['batch_size']
        else:
            return (self.length // self.params['batch_size']) + 1

    def initialize_epoch(self):
        """
        Function called to initialize a new epoch.

        The primary use is to reset ``StatisticsAggregators`` that track statistics over one epoch, e.g.:

            - Average accuracy over the epoch
            - Time taken for the epoch and average per batch
            - etc...

        .. note::


            Empty - To be redefined in inheriting classes.


        """
        pass

    def finalize_epoch(self):
        """
        Function called at the end of an epoch to execute a few tasks, e.g.:

            - Compute the mean accuracy over the epoch,
            - Get the time taken for the epoch and per batch
            - etc.

        This function will use the ``StatisticsAggregators`` set up (or reset) in ``self.initialize_epoch()`.

        .. note::


            Empty - To be redefined in inheriting classes.

            TODO: To display the final results for the current epoch, this function should use the Logger.

        """
        pass

    def plot_preprocessing(self, data_dict, logits):
        """
        Allows for some data preprocessing before the model creates a plot for visualization during training or
        inference.

        .. note::


            Empty - To be redefined in inheriting classes.


        :param data_dict: ``DataDict``.
        :type data_dict: DataDict

        :param logits: Predictions of the model.

        :return: data_dict, logits after preprocessing.

        """
        return data_dict, logits

    def curriculum_learning_initialize(self, curriculum_params):
        """
        Initializes curriculum learning - simply saves the curriculum params.

        .. note::

            This method can be overwritten in the derived classes.


        :param curriculum_params: Interface to parameters accessing curriculum learning view of the registry tree.
        """
        # Save params.
        self.curriculum_params = curriculum_params

    def curriculum_learning_update_params(self, episode):
        """
        Updates problem parameters according to curriculum learning.

        .. note::

            This method can be overwritten in the derived classes.

        :param episode: Number of the current episode.
        :type episode: int

        :return: True informing that Curriculum Learning wasn't active at all (i.e. is finished).

        """

        return True


if __name__ == '__main__':
    """Unit test for DataDict"""

    data_definitions = {'inputs': {'size': [-1, -1, -1], 'type': [int]},
                        'targets': {'size': [-1, -1, -1], 'type': [int]}
                        }

    datadict = DataDict({key: None for key in data_definitions.keys()})

    #datadict['inputs'] = torch.ones([64, 20, 512]).type(torch.FloatTensor)
    #datadict['targets'] = torch.ones([64, 20]).type(torch.FloatTensor)

    print(repr(datadict))
