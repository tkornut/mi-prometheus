#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""maes_module.py: File containing Memory Augmented Encoder-Solver model class."""
__author__ = "Tomasz Kornuta"

from enum import Enum
import torch
from torch import nn
import logging
logger = logging.getLogger('MAES-Model')

# Add path to main project directory.
import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__),  '..', '..')) 
from misc.app_state import AppState
from problems.problem import DataTuple
from models.sequential_model import SequentialModel

from models.encoder_solver.mae_cell import MAECell
from models.encoder_solver.mas_cell import MASCell



class MAES(SequentialModel):
    '''
    Class implementing the Memory Augmented Encoder-Solver (MAES) model. 

    Warning: Class assumes, that the whole batch has the same length, i.e. batch of subsequences 
    becoming input to encoder is of the same length (ends at the same item).
    The same goes to subsequences being input to decoder.
    '''

    def __init__(self, params):
        '''
        Constructor. Initializes parameters on the basis of dictionary passed as argument.
        
        :param params: Dictionary of parameters.
        '''
        # Call base constructor.
        super(MAES, self).__init__(params)

        # Parse parameters.
        # Indices of control bits triggering encoding/decoding. 
        self.encoding_bit =  params['encoding_bit'] # Def: 0
        self.solving_bit =  params['solving_bit'] # Def: 1
        # Check if we want to pass the whole cell state or only the memory.
        self.pass_cell_state = params.get('pass_cell_state', True)

        # It is stored here, but will we used ONLY ONCE - for initialization of memory called from the forward() function.
        self.num_memory_addresses = params['memory']['num_addresses']
        self.num_memory_content_bits = params['memory']['num_content_bits']

        # Save/load encoder.
        self.save_encoder = params.get('save_encoder', False)
        self.load_encoder = params.get('load_encoder', '') # Path+filename to encoder.

        # Create the Encoder cell.
        self.encoder = MAECell(params)

        # Load and freeze encoder - if required.
        if self.load_encoder != '':
            self.encoder.load_state_dict(torch.load(self.load_encoder, map_location=lambda storage, loc: storage))
            logger.info("Encoder imported from {}".format(self.load_encoder))  
            # Freeze weights - TODO: NOT IMPLEMENTED!
            self.encoder.freeze()  
 
        # Create the Decoder/Solver.
        self.solver = MASCell(params)

        # Operation modes.
        self.modes = Enum('Modes', ['Encode', 'Solve'])


    def save(self, model_dir, episode):
        """
        Method saves the model and encoder to file.

        :param model_dir: Directory where the model will be saved.
        :param episode: Episode number used as model identifier.
        :returns: False if saving was successful (TODO: implement true condition if there was an error)
        """
        # Save the model.
        model_filename = 'model_episode_{:05d}.pt'.format(episode)
        torch.save(self.state_dict(), model_dir + model_filename)
        logger.info("Model exported to {}".format(model_dir + model_filename))

        # Additionally, if flag is set to True, save the encoder.
        if self.save_encoder:
            encoder_filename = 'encoder_episode_{:05d}.pt'.format(episode)
            torch.save(self.encoder.state_dict(), model_dir + encoder_filename)
            logger.info("Encoder exported to {}".format(model_dir + encoder_filename))


    def forward(self, data_tuple):
        """
        Forward function accepts a tuple consisting of:
         - a tensor of input data of size [BATCH_SIZE x LENGTH_SIZE x INPUT_SIZE] and 
         - a tensor of targets

        :param data_tuple: Tuple containing inputs and targets.
		:returns: Predictions (logits) being a tensor of size  [BATCH_SIZE x LENGTH_SIZE x OUTPUT_SIZE]. 
        """
        # Get dtype.
        dtype = AppState().dtype

        # Unpack tuple.
        (inputs_BxSxI, _) = data_tuple
        batch_size = inputs_BxSxI.size(0)

        # "Data-driven memory size".
        # Save as TEMPORAL VARIABLE! 
        # (do not overwrite self.num_memory_addresses, which will cause problem with next batch!)
        if self.num_memory_addresses == -1:
            # Set equal to input sequence length.
            num_memory_addresses = inputs_BxSxI.size(1)
        else:
            num_memory_addresses = self.num_memory_addresses
 
        # Initialize memory [BATCH_SIZE x MEMORY_ADDRESSES x CONTENT_BITS] 
        init_memory_BxAxC = torch.zeros(batch_size,  num_memory_addresses,  self.num_memory_content_bits).type(dtype)

        # Initialize 'zero' state.
        encoder_state = self.encoder.init_state(init_memory_BxAxC)
        solver_state = None # For now, it will be set during execution.

        # Start as encoder.
        mode = self.modes.Encode

        # Logits container.
        logits = []

        for x in inputs_BxSxI.chunk(inputs_BxSxI.size(1), dim=1):
            # Squeeze x.
            x = x.squeeze(1)

            # Switch between the encoder and solver modes.
            if x[0, self.solving_bit] and not x[0, self.encoding_bit]:
                mode = self.modes.Solve
                if self.pass_cell_state:
                    # Initialize solver state with final encoder state.
                    solver_state = self.solver.init_state_with_encoder_state(encoder_state)
                else:
                    # Initialize solver state - with final state of memory and final attention only.
                    solver_state = self.solver.init_state(encoder_state.memory_state, encoder_state.interface_state.attention)

            elif x[0, self.encoding_bit] and x[0, self.solving_bit]:
                logger.error('Two control bits were on:\n {}'.format(x))
                exit(-1)

            # Run encoder or solver - depending on the state.
            if mode == self.modes.Encode:
                logit, encoder_state = self.encoder(x, encoder_state)
            elif mode == self.modes.Solve:
                logit, solver_state = self.solver(x, solver_state)
                            
            # Collect logits from both encoder and solver - they will be masked afterwards.
            logits += [logit]

        # Stack logits along the temporal (sequence) axis.
        logits = torch.stack(logits, 1)
        return logits





if __name__ == "__main__":
    # Set logging level.
    logger = logging.getLogger('MAES')
    logging.basicConfig(level=logging.DEBUG)
    
    # Set visualization.
    from misc.app_state import AppState
    AppState().visualize = True

    # "Loaded parameters".
    params = {'num_control_bits': 3, 'num_data_bits': 8, # input and output size
        'encoding_bit': 0, 'solving_bit': 1,
        'controller': {'name': 'rnn', 'hidden_state_size': 20, 'num_layers': 1, 'non_linearity': 'sigmoid'},  # controller parameters
        'interface': {'shift_size': 3},  # interface parameters
        'memory': {'num_addresses' :-1, 'num_content_bits': 11}, # memory parameters
        'visualization_mode': 2
        }  
    logger.debug("params: {}".format(params))  
    
    input_size = params["num_control_bits"] + params["num_data_bits"]
    output_size = params["num_data_bits"]
        
    seq_length = 1
    batch_size = 2
    
    # Construct our model by instantiating the class defined above.
    model = MAES(params)
    

    # Check for different seq_lengts and batch_sizes.
    for i in range(2):
        # Create random Tensors to hold inputs and outputs
        enc = torch.zeros(batch_size, 1, input_size)
        enc[:, 0, params['encoding_bit']] = 1
        data = torch.randn(batch_size, seq_length,   input_size)
        data[:,:, 0:1] = 0
        dec = torch.zeros(batch_size, 1, input_size)
        dec[:, 0, params['solving_bit']] = 1
        dummy = torch.zeros(batch_size, seq_length, input_size)
        x = torch.cat([enc, data, dec, dummy], dim=1)
        # Output        
        y = torch.randn(batch_size, 2+2*seq_length,  output_size)
        dt = DataTuple(x,y)

        # Test forward pass.
        logger.info("------- forward -------")
        y_pred = model(dt)

        logger.info("------- result -------")
        logger.info("input {}:\n {}".format(x.size(), x))
        logger.info("target.size():\n {}".format(y.size()))
        logger.info("prediction {}:\n {}".format(y_pred.size(), y_pred))

        # Plot it and check whether window was closed or not. 
        if model.plot(dt, y_pred):
            break

        # Change batch size and seq_length.
        seq_length = seq_length+1
        batch_size = batch_size+1
    