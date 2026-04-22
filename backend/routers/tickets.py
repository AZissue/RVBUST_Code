"""
工单管理路由
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import Optional, List
from datetime import datetime

from database import get_db
from models import Ticket, Customer, FollowUp
from schemas import (
    success_response, error_response,
    TicketCreate, TicketUpdate, TicketResponse,
    TicketListResponse, TicketStatusUpdate, QuickTicketCreate
)

router = APIRouter()


@router.get("", response_model=dict)
def get_tickets(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    customer_id: Optional[int] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db)
):
    """工单列表（支持筛选、排序、分页）"""
    query = db.query(Ticket, Customer).join(Customer, Ticket.customer_id == Customer.id)
    
    # 筛选条件
    if status:
        query = query.filter(Ticket.status == status)
    if assignee:
        query = query.filter(Ticket.assignee == assignee)
    if customer_id:
        query = query.filter(Ticket.customer_id == customer_id)
    if category:
        query = query.filter(Ticket.category == category)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Ticket.title.ilike(search),
                Ticket.description.ilike(search),
                Customer.name.ilike(search)
            )
        )
    
    # 排序
    sort_column = getattr(Ticket, sort_by, Ticket.created_at)
    if sort_order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())
    
    total = query.count()
    results = query.offset((page - 1) * page_size).limit(page_size).all()
    
    items = []
    for ticket, customer in results:
        item = TicketListResponse.model_validate(ticket)
        item_dict = item.model_dump()
        item_dict["customer_name"] = customer.name
        items.append(item_dict)
    
    return success_response({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    })


@router.get("/{ticket_id}", response_model=dict)
def get_ticket_detail(ticket_id: int, db: Session = Depends(get_db)):
    """工单详情"""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        return error_response("工单不存在", 404)
    
    result = TicketResponse.model_validate(ticket)
    result_dict = result.model_dump()
    result_dict["customer"] = {
        "id": ticket.customer.id,
        "name": ticket.customer.name,
        "contact_person": ticket.customer.contact_person,
        "phone": ticket.customer.phone
    }
    result_dict["follow_ups"] = [
        {
            "id": f.id,
            "content": f.content,
            "type": f.type,
            "created_by": f.created_by,
            "created_at": f.created_at.isoformat() if f.created_at else None
        }
        for f in ticket.follow_ups
    ]
    
    return success_response(result_dict)


@router.post("", response_model=dict)
def create_ticket(ticket: TicketCreate, db: Session = Depends(get_db)):
    """创建工单"""
    db_ticket = Ticket(**ticket.model_dump())
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    
    # 自动创建系统跟进记录
    follow = FollowUp(
        ticket_id=db_ticket.id,
        content="工单已创建",
        type="system",
        created_by="系统"
    )
    db.add(follow)
    db.commit()
    
    return success_response(TicketResponse.model_validate(db_ticket).model_dump(), "创建成功")


@router.post("/quick", response_model=dict)
def quick_create_ticket(data: QuickTicketCreate, db: Session = Depends(get_db)):
    """快速创建工单（首页用）"""
    # 查找或创建客户
    customer = db.query(Customer).filter(Customer.name == data.customer_name).first()
    if not customer:
        customer = Customer(name=data.customer_name)
        db.add(customer)
        db.commit()
        db.refresh(customer)
    
    # 更新客户最后联系时间
    customer.last_contact_at = datetime.now()
    
    # 创建工单
    db_ticket = Ticket(
        customer_id=customer.id,
        title=data.title,
        category=data.category,
        description=data.description,
        priority=data.priority or "normal",
        assignee=data.assignee
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    
    # 系统记录
    follow = FollowUp(
        ticket_id=db_ticket.id,
        content="工单已创建",
        type="system",
        created_by="系统"
    )
    db.add(follow)
    db.commit()
    
    return success_response({
        "ticket_id": db_ticket.id,
        "customer_id": customer.id,
        "customer_name": customer.name
    }, "创建成功")


@router.put("/{ticket_id}", response_model=dict)
def update_ticket(ticket_id: int, ticket: TicketUpdate, db: Session = Depends(get_db)):
    """更新工单"""
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not db_ticket:
        return error_response("工单不存在", 404)
    
    update_data = ticket.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_ticket, field, value)
    
    db.commit()
    db.refresh(db_ticket)
    
    return success_response(TicketResponse.model_validate(db_ticket).model_dump(), "更新成功")


@router.put("/{ticket_id}/status", response_model=dict)
def update_ticket_status(ticket_id: int, data: TicketStatusUpdate, db: Session = Depends(get_db)):
    """更新工单状态（专用接口，记录时间）"""
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not db_ticket:
        return error_response("工单不存在", 404)
    
    old_status = db_ticket.status
    new_status = data.status
    
    # 更新状态和时间戳
    db_ticket.status = new_status
    now = datetime.now()
    
    if new_status == "processing" and not db_ticket.started_at:
        db_ticket.started_at = now
    elif new_status == "resolved" and not db_ticket.resolved_at:
        db_ticket.resolved_at = now
    elif new_status == "closed" and not db_ticket.closed_at:
        db_ticket.closed_at = now
    
    db.commit()
    db.refresh(db_ticket)
    
    # 记录状态变更跟进
    status_map = {
        "pending": "待处理",
        "processing": "处理中",
        "waiting_feedback": "等待反馈",
        "resolved": "已解决",
        "closed": "已关闭"
    }
    follow = FollowUp(
        ticket_id=ticket_id,
        content=f"状态变更：{status_map.get(old_status, old_status)} → {status_map.get(new_status, new_status)}",
        type="system",
        created_by="系统"
    )
    db.add(follow)
    db.commit()
    
    return success_response(TicketResponse.model_validate(db_ticket).model_dump(), "状态更新成功")


@router.delete("/{ticket_id}", response_model=dict)
def delete_ticket(ticket_id: int, db: Session = Depends(get_db)):
    """删除工单"""
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not db_ticket:
        return error_response("工单不存在", 404)
    
    db.delete(db_ticket)
    db.commit()
    
    return success_response(message="删除成功")
