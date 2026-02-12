import sys
import os
from pathlib import Path

# 获取项目根目录
root_dir = Path(__file__).parent.parent.resolve()

# 将根目录添加到 sys.path
sys.path.insert(0, str(root_dir))
