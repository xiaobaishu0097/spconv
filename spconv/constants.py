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

import os
from pathlib import Path
from typing import List
from pccm.utils import project_is_editable, project_is_installed

PACKAGE_NAME = "spconv"
PACKAGE_ROOT = Path(__file__).parent.resolve()

EDITABLE_INSTALLED = project_is_installed(PACKAGE_NAME) and project_is_editable(PACKAGE_NAME)


_filter_hwio_env = os.getenv("SPCONV_FILTER_HWIO", "0")
FILTER_HWIO = _filter_hwio_env == "1"