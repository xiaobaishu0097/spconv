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

from cumm import tensorview as tv 
import torch 
from typing import Optional, List
_TORCH_DTYPE_TO_TV = {
    torch.float32: tv.float32,
    torch.float64: tv.float64,
    torch.float16: tv.float16,
    torch.int32: tv.int32,
    torch.int64: tv.int64,
    torch.int8: tv.int8,
    torch.int16: tv.int16,
    torch.uint8: tv.uint8,
}

def torch_tensor_to_tv(ten: torch.Tensor, dtype: Optional[int] = None, shape: Optional[List[int]] = None):
    assert ten.is_contiguous(), "must be contiguous tensor"
    ptr = ten.data_ptr()
    device = ten.device 
    if device.type == "cpu":
        tv_device = -1
    elif device.type == "cuda":
        tv_device = 0
    else:
        raise NotImplementedError
    if shape is None:
        shape = list(ten.shape)
    if dtype is None:
        dtype = _TORCH_DTYPE_TO_TV[ten.dtype]
    return tv.from_blob(ptr, shape, dtype, tv_device)

def get_current_stream():
    return torch.cuda.current_stream().cuda_stream

if __name__ == "__main__":
    a = torch.rand(2, 2)
    atv = torch_tensor_to_tv(a)
    print(atv.numpy_view())