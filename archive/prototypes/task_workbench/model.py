"""Interaction-only state model. No SDK, geometry algorithm or session writes."""
from dataclasses import dataclass, field


@dataclass
class Workflow:
    inputs: list = field(default_factory=list)
    results: list = field(default_factory=list)
    selected: str = '机位 001'
    parameter: float = 1.0
    revision: int = 0
    serial: int = 0
    active: object = None
    candidate: object = None
    stopping: bool = False
    message: str = '请选择至少两项处理输入。'

    @property
    def busy(self):
        return self.active is not None

    @property
    def can_publish(self):
        return not self.busy and self.candidate is not None and self.candidate[1] == self.revision

    def select(self, name):
        self.selected = name

    def invalidate(self):
        self.revision += 1
        self.candidate = None
        self.message = '输入或参数已变化，需重新计算。'

    def set_inputs(self, names):
        names = list(dict.fromkeys(names))
        if names != self.inputs:
            self.inputs = names
            self.invalidate()

    def set_parameter(self, value):
        if value != self.parameter:
            self.parameter = value
            self.invalidate()

    def start(self):
        if self.busy:
            raise ValueError('当前任务尚未结束')
        if len(self.inputs) < 2:
            raise ValueError('请在左侧勾选至少两项处理输入')
        self.serial += 1
        self.active = (self.serial, self.revision)
        self.candidate = None
        self.stopping = False
        self.message = '演练计算中；可安全停止。'
        return self.active

    def stop(self):
        if self.busy:
            self.stopping = True
            self.message = '正在安全停止，等待在途步骤结束。'

    def complete(self, token, failed=False):
        if token != self.active or not self.busy:
            return False
        self.active = None
        if self.stopping:
            self.message = '已安全停止；保留输入与参数，可重试。'
        elif token[1] != self.revision:
            self.message = '输入已变化，已拒绝过期结果；请重新计算。'
        elif failed:
            self.message = '演练失败：重合不足。保留输入与参数，请调整后重试。'
        else:
            self.candidate = token
            self.message = '候选就绪（模拟）；检查后生成演练结果。'
            return True
        return False

    def publish(self):
        if not self.can_publish:
            raise ValueError('没有有效候选，请先计算')
        name = f'演练结果 {len(self.results) + 1:03d}'
        self.results.append(name)
        self.selected = name
        self.candidate = None
        self.message = f'{name}已加入演练数据；原始输入保留，未写入磁盘。'
        return name
