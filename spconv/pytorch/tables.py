# Copyright 2021 Yan Yan
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import torch
from torch.autograd import Function

import spconv.pytorch as spconv
#from torch.nn import Module
from spconv.pytorch.modules import SparseModule


class JoinTable(SparseModule):  # Module):
    def forward(self, input):
        output = spconv.SparseConvTensor(
            torch.cat([i.features for i in input], 1), input[1].indices,
            input[1].spatial_shape, input[0].batch_size)
        output.indice_dict = input[1].indice_dict
        output.grid = input[1].grid
        return output

    def input_spatial_size(self, out_size):
        return out_size


class AddTable(SparseModule):  # Module):
    def forward(self, input):
        output = spconv.SparseConvTensor(sum([i.features for i in input]),
                                         input[1].indices,
                                         input[1].spatial_shape,
                                         input[1].batch_size)
        output.indice_dict = input[1].indice_dict
        output.grid = input[1].grid

        return output

    def input_spatial_size(self, out_size):
        return out_size


class ConcatTable(SparseModule):  # Module):
    def forward(self, input):
        return [module(input) for module in self._modules.values()]

    def add(self, module):
        self._modules[str(len(self._modules))] = module
        return self

    def input_spatial_size(self, out_size):
        return self._modules['0'].input_spatial_size(out_size)
