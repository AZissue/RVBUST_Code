"""
Pydantic 数据模型（请求/响应校验）
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List


# ==================== 通用响应包装 ====================
class ResponseModel(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None


def success_response(data=None, message="success"):
    return {"code": 200, "message": message, "data": data}


def error_response(message="error", code=400):
    return {"code": code, "message": message, "data": None}


# ==================== Customer 模型 ====================
class CustomerBase(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    activity_level: Optional[str] = "medium"


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    activity_level: Optional[str] = None


class CustomerResponse(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    created_at: Optional[datetime] = None
    last_contact_at: Optional[datetime] = None


# ==================== Device 模型 ====================
class DeviceBase(BaseModel):
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    purchase_date: Optional[datetime] = None


class DeviceCreate(DeviceBase):
    customer_id: int


class DeviceResponse(DeviceBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    customer_id: int
    created_at: Optional[datetime] = None


# ==================== Ticket 模型 ====================
class TicketBase(BaseModel):
    title: str
    category: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = "normal"
    assignee: Optional[str] = None


class TicketCreate(TicketBase):
    customer_id: int
    device_id: Optional[int] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    solution: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None


class TicketStatusUpdate(BaseModel):
    status: str


class TicketResponse(TicketBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    customer_id: int
    device_id: Optional[int] = None
    status: str
    solution: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # 关联数据
    customer: Optional[CustomerResponse] = None


class TicketListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    customer_id: int
    title: str
    category: Optional[str] = None
    status: str
    priority: str
    assignee: Optional[str] = None
    created_at: Optional[datetime] = None


# ==================== FollowUp 模型 ====================
class FollowUpBase(BaseModel):
    content: str
    type: Optional[str] = "comment"


class FollowUpCreate(FollowUpBase):
    ticket_id: int
    created_by: Optional[str] = None


class FollowUpResponse(FollowUpBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    ticket_id: int
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


# ==================== Dashboard 模型 ====================
class DashboardStats(BaseModel):
    pending_count: int
    processing_count: int
    waiting_feedback_count: int
    resolved_today_count: int


class TodoItem(BaseModel):
    id: int
    title: str
    customer_name: str
    status: str
    priority: str
    created_at: Optional[datetime] = None
    is_overdue: bool = False


class QuickTicketCreate(BaseModel):
    customer_name: str
    title: str
    category: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[str] = "normal"


# ==================== 客户搜索 ====================
class CustomerSearchResult(BaseModel):
    id: int
    name: str
    contact_person: Optional[str] = None
    region: Optional[str] = None


# ==================== 客户详情（含时间轴）====================
class TimelineItem(BaseModel):
    id: int
    type: str  # ticket / follow_up
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class CustomerDetailResponse(CustomerResponse):
    devices: List[DeviceResponse] = []
    timeline: List[TimelineItem] = []
