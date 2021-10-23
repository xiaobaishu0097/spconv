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

import math
import time
from typing import List, Optional, Tuple, Union

import numpy as np
import torch
from torch import nn
from torch.nn import init
from torch.nn.parameter import Parameter

from spconv import pytorch as spconv
from spconv.algo import ConvAlgo
import spconv.pytorch.functional as Fsp
from spconv.pytorch import ops
from spconv.pytorch.core import IndiceData, SparseConvTensor
from spconv.pytorch.modules import SparseModule
from spconv.constants import FILTER_HWIO

def _calculate_fan_in_and_fan_out_hwio(tensor):
    dimensions = tensor.ndimension()
    if dimensions < 2:
        raise ValueError(
            "Fan in and fan out can not be computed for tensor with fewer than 2 dimensions"
        )

    if dimensions == 2:  # Linear
        fan_in = tensor.size(-2)
        fan_out = tensor.size(-1)
    else:
        if FILTER_HWIO:
            num_input_fmaps = tensor.size(-2)
            num_output_fmaps = tensor.size(-1)
        else:
            num_input_fmaps = tensor.size(-1)
            num_output_fmaps = tensor.size(-2)
        receptive_field_size = 1
        if tensor.dim() > 2:
            receptive_field_size = tensor[..., 0, 0].numel()
        fan_in = num_input_fmaps * receptive_field_size
        fan_out = num_output_fmaps * receptive_field_size

    return fan_in, fan_out


class SparseConvolution(SparseModule):
    __constants__ = [
        'stride', 'padding', 'dilation', 'groups', 'bias', 'subm', 'inverse',
        'transposed', 'output_padding', 'fused_bn'
    ]

    def __init__(self,
                 ndim: int,
                 in_channels: int,
                 out_channels: int,
                 kernel_size: Union[int, List[int], Tuple[int, ...]]=3,
                 stride: Union[int, List[int], Tuple[int, ...]]=1,
                 padding: Union[int, List[int], Tuple[int, ...]]=0,
                 dilation: Union[int, List[int], Tuple[int, ...]]=1,
                 groups: Union[int, List[int], Tuple[int, ...]]=1,
                 bias: bool=True,
                 subm: bool=False,
                 output_padding: Union[int, List[int], Tuple[int, ...]]=0,
                 transposed: bool=False,
                 inverse: bool=False,
                 indice_key: Optional[str]=None,
                 fused_bn: bool=False,
                 algo: ops.ConvAlgo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConvolution, self).__init__(name=name)
        assert groups == 1
        if not isinstance(kernel_size, (list, tuple)):
            kernel_size = [kernel_size] * ndim
        if not isinstance(stride, (list, tuple)):
            stride = [stride] * ndim
        if not isinstance(padding, (list, tuple)):
            padding = [padding] * ndim
        if not isinstance(dilation, (list, tuple)):
            dilation = [dilation] * ndim
        if not isinstance(output_padding, (list, tuple)):
            output_padding = [output_padding] * ndim
        self.ndim = ndim
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.conv1x1 = np.prod(kernel_size) == 1
        self.stride = stride
        self.padding = padding
        self.dilation = dilation
        self.transposed = transposed
        self.inverse = inverse
        self.output_padding = output_padding
        self.groups = groups
        self.subm = subm
        self.indice_key = indice_key
        self.fused_bn = fused_bn
        self.algo = algo
        if FILTER_HWIO:
            self.weight = Parameter(
                torch.Tensor(*kernel_size, in_channels, out_channels))
        else:
            self.weight = Parameter(
                torch.Tensor(*kernel_size, out_channels, in_channels))
        if bias:
            self.bias = Parameter(torch.Tensor(out_channels))
        else:
            self.register_parameter('bias', None)
        self.reset_parameters()

    def reset_parameters(self):
        n = self.in_channels
        # init.uniform_(self.weight, 0, 0.001)
        init.kaiming_uniform_(self.weight, a=math.sqrt(0.005))
        if self.bias is not None:
            fan_in, _ = _calculate_fan_in_and_fan_out_hwio(self.weight)
            bound = 1 / math.sqrt(fan_in)
            init.uniform_(self.bias, -bound, bound)

    def forward(self, input: SparseConvTensor):
        assert isinstance(input, SparseConvTensor)
        features = input.features
        device = features.device
        indices = input.indices
        spatial_shape = input.spatial_shape
        batch_size = input.batch_size
        if not self.subm:
            if self.transposed:
                out_spatial_shape = ops.get_deconv_output_size(
                    spatial_shape, self.kernel_size, self.stride, self.padding,
                    self.dilation, self.output_padding)
            else:
                out_spatial_shape = ops.get_conv_output_size(
                    spatial_shape, self.kernel_size, self.stride, self.padding,
                    self.dilation)
        else:
            out_spatial_shape = spatial_shape
        # input.update_grid(out_spatial_shape)
        # t = time.time()
        out_tensor = input.shadow_copy()
        if input.benchmark:
            if self.name is None:
                raise ValueError(
                    "you need to assign name to spmodules before benchmark (spconv.utils.bench.assign_name_to_spmod)"
                )
            if self.name not in input.benchmark_record:
                input.benchmark_record[self.name] = {
                    "type": "SparseConvolution",
                    "indice_gen_time": [],
                    "time": [],
                    "num_points": [],
                    "num_out_points": [],
                    "params": {
                        "kernel_size": self.kernel_size,
                        "stride": self.stride,
                        "padding": self.padding,
                        "dilation": self.dilation,
                        "output_padding": self.output_padding,
                        "subm": self.subm,
                        "transposed": self.transposed,
                        "input_channels": self.in_channels,
                        "out_channels": self.out_channels,
                    }
                }
        if self.conv1x1:
            if FILTER_HWIO:
                features = torch.mm(
                    input.features,
                    self.weight.view(self.out_channels, self.in_channels).T)
            else:
                features = torch.mm(
                    input.features,
                    self.weight.view(self.in_channels, self.out_channels))

            if self.bias is not None:
                features += self.bias
            out_tensor = out_tensor.replace_feature(features)
            return out_tensor
        datas = input.find_indice_pair(self.indice_key)
        if self.inverse:
            assert datas is not None and self.indice_key is not None
            outids = datas.indices
            indice_pairs = datas.indice_pairs
            indice_pair_num = datas.indice_pair_num
            out_spatial_shape = datas.out_spatial_shape
            assert indice_pair_num.shape[0] == np.prod(
                self.kernel_size
            ), "inverse conv must have same kernel size as its couple conv"
        else:
            if self.indice_key is not None and datas is not None:
                outids = datas.out_indices
                indice_pairs = datas.indice_pairs
                indice_pair_num = datas.indice_pair_num
            else:
                if input.benchmark:
                    torch.cuda.synchronize()
                    t = time.time()
                outids, indice_pairs, indice_pair_num = ops.get_indice_pairs(
                    indices,
                    batch_size,
                    spatial_shape,
                    self.algo,
                    self.kernel_size,
                    self.stride,
                    self.padding,
                    self.dilation,
                    self.output_padding,
                    self.subm,
                    self.transposed)
                if input.benchmark:
                    torch.cuda.synchronize()
                    interval = time.time() - t
                    out_tensor.benchmark_record[
                        self.name]["indice_gen_time"].append(interval)

                indice_data = IndiceData(outids, indices, indice_pairs,
                                         indice_pair_num, spatial_shape)
                input.indice_dict[self.indice_key] = indice_data
        if input.benchmark:
            torch.cuda.synchronize()
            t = time.time()

        if self.fused_bn:
            raise NotImplementedError
            assert self.bias is not None
            out_features = ops.fused_indice_conv(features, self.weight,
                                                 self.bias,
                                                 indice_pairs.to(device),
                                                 indice_pair_num,
                                                 outids.shape[0], self.inverse,
                                                 self.subm)
        else:
            if self.subm:
                out_features = Fsp.indice_subm_conv(features, self.weight,
                                                    indice_pairs.to(device),
                                                    indice_pair_num,
                                                    outids.shape[0], self.algo)
            else:
                if self.inverse:
                    out_features = Fsp.indice_inverse_conv(
                        features, self.weight, indice_pairs.to(device),
                        indice_pair_num, outids.shape[0], self.algo)
                else:
                    out_features = Fsp.indice_conv(features, self.weight,
                                                   indice_pairs.to(device),
                                                   indice_pair_num,
                                                   outids.shape[0], self.algo)

            if self.bias is not None:
                out_features += self.bias
        if input.benchmark:
            torch.cuda.synchronize()
            interval = time.time() - t
            out_tensor.benchmark_record[self.name]["time"].append(interval)
            out_tensor.benchmark_record[self.name]["num_points"].append(
                features.shape[0])
            out_tensor.benchmark_record[self.name]["num_out_points"].append(
                out_features.shape[0])
        out_tensor = out_tensor.replace_feature(out_features)
        out_tensor.indices = outids
        out_tensor.spatial_shape = out_spatial_shape
        return out_tensor

class SparseConv1d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConv1d, self).__init__(1,
                                           in_channels,
                                           out_channels,
                                           kernel_size,
                                           stride,
                                           padding,
                                           dilation,
                                           groups,
                                           bias,
                                           indice_key=indice_key,
                                           algo=algo,
                                           name=name)


class SparseConv2d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConv2d, self).__init__(2,
                                           in_channels,
                                           out_channels,
                                           kernel_size,
                                           stride,
                                           padding,
                                           dilation,
                                           groups,
                                           bias,
                                           indice_key=indice_key,
                                           algo=algo,
                                           name=name)


class SparseConv3d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConv3d, self).__init__(3,
                                           in_channels,
                                           out_channels,
                                           kernel_size,
                                           stride,
                                           padding,
                                           dilation,
                                           groups,
                                           bias,
                                           indice_key=indice_key,
                                           algo=algo,
                                           name=name)


class SparseConv4d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConv4d, self).__init__(4,
                                           in_channels,
                                           out_channels,
                                           kernel_size,
                                           stride,
                                           padding,
                                           dilation,
                                           groups,
                                           bias,
                                           indice_key=indice_key,
                                           algo=algo,
                                           name=name)


class SparseConvTranspose1d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConvTranspose1d, self).__init__(1,
                                                    in_channels,
                                                    out_channels,
                                                    kernel_size,
                                                    stride,
                                                    padding,
                                                    dilation,
                                                    groups,
                                                    bias,
                                                    transposed=True,
                                                    indice_key=indice_key,
                                                    algo=algo,
                                                    name=name)


class SparseConvTranspose2d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConvTranspose2d, self).__init__(2,
                                                    in_channels,
                                                    out_channels,
                                                    kernel_size,
                                                    stride,
                                                    padding,
                                                    dilation,
                                                    groups,
                                                    bias,
                                                    transposed=True,
                                                    indice_key=indice_key,
                                                    algo=algo,
                                                    name=name)


class SparseConvTranspose3d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConvTranspose3d, self).__init__(3,
                                                    in_channels,
                                                    out_channels,
                                                    kernel_size,
                                                    stride,
                                                    padding,
                                                    dilation,
                                                    groups,
                                                    bias,
                                                    transposed=True,
                                                    indice_key=indice_key,
                                                    algo=algo,
                                                    name=name)

class SparseConvTranspose4d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseConvTranspose4d, self).__init__(4,
                                                    in_channels,
                                                    out_channels,
                                                    kernel_size,
                                                    stride,
                                                    padding,
                                                    dilation,
                                                    groups,
                                                    bias,
                                                    transposed=True,
                                                    indice_key=indice_key,
                                                    algo=algo,
                                                    name=name)


class SparseInverseConv1d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 indice_key,
                 bias=True,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseInverseConv1d, self).__init__(1,
                                                  in_channels,
                                                  out_channels,
                                                  kernel_size,
                                                  bias=bias,
                                                  inverse=True,
                                                  indice_key=indice_key,
                                                  algo=algo,
                                                  name=name)


class SparseInverseConv2d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 indice_key,
                 bias=True,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseInverseConv2d, self).__init__(2,
                                                  in_channels,
                                                  out_channels,
                                                  kernel_size,
                                                  bias=bias,
                                                  inverse=True,
                                                  indice_key=indice_key,
                                                  algo=algo,
                                                  name=name)


class SparseInverseConv3d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 indice_key,
                 bias=True,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseInverseConv3d, self).__init__(3,
                                                  in_channels,
                                                  out_channels,
                                                  kernel_size,
                                                  bias=bias,
                                                  inverse=True,
                                                  indice_key=indice_key,
                                                  algo=algo,
                                                  name=name)

class SparseInverseConv4d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 indice_key,
                 bias=True,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SparseInverseConv4d, self).__init__(4,
                                                  in_channels,
                                                  out_channels,
                                                  kernel_size,
                                                  bias=bias,
                                                  inverse=True,
                                                  indice_key=indice_key,
                                                  algo=algo,
                                                  name=name)

class SubMConv1d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SubMConv1d, self).__init__(1,
                                         in_channels,
                                         out_channels,
                                         kernel_size,
                                         stride,
                                         padding,
                                         dilation,
                                         groups,
                                         bias,
                                         True,
                                         indice_key=indice_key,
                                         algo=algo,
                                         name=name)


class SubMConv2d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SubMConv2d, self).__init__(2,
                                         in_channels,
                                         out_channels,
                                         kernel_size,
                                         stride,
                                         padding,
                                         dilation,
                                         groups,
                                         bias,
                                         True,
                                         indice_key=indice_key,
                                         algo=algo,
                                         name=name)


class SubMConv3d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SubMConv3d, self).__init__(3,
                                         in_channels,
                                         out_channels,
                                         kernel_size,
                                         stride,
                                         padding,
                                         dilation,
                                         groups,
                                         bias,
                                         True,
                                         indice_key=indice_key,
                                         algo=algo,
                                         name=name)


class SubMConv4d(SparseConvolution):
    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size,
                 stride=1,
                 padding=0,
                 dilation=1,
                 groups=1,
                 bias=True,
                 indice_key=None,
                 algo=ops.ConvAlgo.Native,
                 name=None):
        super(SubMConv4d, self).__init__(4,
                                         in_channels,
                                         out_channels,
                                         kernel_size,
                                         stride,
                                         padding,
                                         dilation,
                                         groups,
                                         bias,
                                         True,
                                         indice_key=indice_key,
                                         algo=algo,
                                         name=name)
