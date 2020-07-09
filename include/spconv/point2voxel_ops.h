// Copyright 2020 xmyqsh
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once

#include <spconv/points2voxels.h>
#include <tensorview/torch_utils.h>
#include <torch/script.h>
#include <utility/timer.h>

namespace spconv {

int64_t pointsToVoxel(torch::Tensor points, torch::Tensor indexes,
                      torch::Tensor pointIndex, torch::Tensor grids,
                      torch::Tensor numPointsPerGrid, torch::Tensor voxels,
                      torch::Tensor coors, std::vector<int64_t> gridShape,
                      const int64_t ndim);

} // namespace spconv