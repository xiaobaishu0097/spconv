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
from torch import nn
from torch.autograd import Function

import spconv.pytorch.ops as ops


class SparseConvFunction(Function):
    @staticmethod
    def forward(ctx, features, filters, indice_pairs, indice_pair_num,
                num_activate_out, algo):
        ctx.save_for_backward(indice_pairs, indice_pair_num, features, filters)
        ctx.algo = algo
        return ops.indice_conv(features,
                               filters,
                               indice_pairs,
                               indice_pair_num,
                               num_activate_out,
                               False,
                               algo=algo)

    @staticmethod
    def backward(ctx, grad_output):
        indice_pairs, indice_pair_num, features, filters = ctx.saved_tensors

        input_bp, filters_bp = ops.indice_conv_backward(features,
                                                        filters,
                                                        grad_output.contiguous(),
                                                        indice_pairs,
                                                        indice_pair_num,
                                                        False,
                                                        algo=ctx.algo)

        return input_bp, filters_bp, None, None, None, None


class SparseInverseConvFunction(Function):
    @staticmethod
    def forward(ctx, features, filters, indice_pairs, indice_pair_num,
                num_activate_out, algo):
        ctx.save_for_backward(indice_pairs, indice_pair_num, features, filters)
        ctx.algo = algo
        return ops.indice_conv(features,
                               filters,
                               indice_pairs,
                               indice_pair_num,
                               num_activate_out,
                               True,
                               False,
                               algo=algo)

    @staticmethod
    def backward(ctx, grad_output):
        indice_pairs, indice_pair_num, features, filters = ctx.saved_tensors
        input_bp, filters_bp = ops.indice_conv_backward(features,
                                                        filters,
                                                        grad_output.contiguous(),
                                                        indice_pairs,
                                                        indice_pair_num,
                                                        True,
                                                        False,
                                                        algo=ctx.algo)

        return input_bp, filters_bp, None, None, None, None


class SubMConvFunction(Function):
    @staticmethod
    def forward(ctx, features, filters, indice_pairs, indice_pair_num,
                num_activate_out, algo):
        ctx.save_for_backward(indice_pairs, indice_pair_num, features, filters)
        ctx.algo = algo
        return ops.indice_conv(features,
                               filters,
                               indice_pairs,
                               indice_pair_num,
                               num_activate_out,
                               False,
                               True,
                               algo=algo)

    @staticmethod
    def backward(ctx, grad_output):
        indice_pairs, indice_pair_num, features, filters = ctx.saved_tensors
        input_bp, filters_bp = ops.indice_conv_backward(features,
                                                        filters,
                                                        grad_output.contiguous(),
                                                        indice_pairs,
                                                        indice_pair_num,
                                                        False,
                                                        True,
                                                        algo=ctx.algo)

        return input_bp, filters_bp, None, None, None, None


class SparseMaxPoolFunction(Function):
    @staticmethod
    def forward(ctx, features, indice_pairs, indice_pair_num,
                num_activate_out):
        out = ops.indice_maxpool(features, indice_pairs, indice_pair_num,
                                 num_activate_out)
        ctx.save_for_backward(indice_pairs, indice_pair_num, features, out)
        return out

    @staticmethod
    def backward(ctx, grad_output):
        indice_pairs, indice_pair_num, features, out = ctx.saved_tensors
        input_bp = ops.indice_maxpool_backward(features, out, grad_output.contiguous(),
                                               indice_pairs, indice_pair_num)
        return input_bp, None, None, None


indice_conv = SparseConvFunction.apply
indice_inverse_conv = SparseInverseConvFunction.apply
indice_subm_conv = SubMConvFunction.apply
indice_maxpool = SparseMaxPoolFunction.apply
