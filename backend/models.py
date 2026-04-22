"""
SQLAlchemy 数据库模型
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class Customer(Base):
    """客户档案"""
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    contact_person = Column(String(50))
    phone = Column(String(20))
    email = Column(String(100))
    region = Column(String(50))
    industry = Column(String(50))
    created_at = Column(DateTime, server_default=func.current_timestamp())
    last_contact_at = Column(DateTime)
    activity_level = Column(String(20), default="medium")  # high/medium/low
    
    # 关联关系
    devices = relationship("Device", back_populates="customer", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="customer", cascade="all, delete-orphan")


class Device(Base):
    """设备信息"""
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    model = Column(String(50))
    serial_number = Column(String(100))
    firmware_version = Column(String(50))
    purchase_date = Column(DateTime)
    created_at = Column(DateTime, server_default=func.current_timestamp())
    
    customer = relationship("Customer", back_populates="devices")


class Ticket(Base):
    """工单"""
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    title = Column(String(200), nullable=False)
    category = Column(String(50))  # 硬件故障/软件使用/咨询/投诉/其他
    description = Column(Text)
    solution = Column(Text)
    status = Column(String(20), default="pending")  # pending/processing/waiting_feedback/resolved/closed
    priority = Column(String(20), default="normal")  # urgent/high/normal/low
    assignee = Column(String(50))
    created_at = Column(DateTime, server_default=func.current_timestamp())
    started_at = Column(DateTime)
    resolved_at = Column(DateTime)
    closed_at = Column(DateTime)
    
    customer = relationship("Customer", back_populates="tickets")
    follow_ups = relationship("FollowUp", back_populates="ticket", cascade="all, delete-orphan", order_by="FollowUp.created_at.desc()")


class FollowUp(Base):
    """跟进记录"""
    __tablename__ = "follow_ups"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String(20), default="comment")  # comment/status_change/system
    created_by = Column(String(50))
    created_at = Column(DateTime, server_default=func.current_timestamp())
    
    ticket = relationship("Ticket", back_populates="follow_ups")
